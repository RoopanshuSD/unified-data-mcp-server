"""The policy core, independent of transport: RBAC -> rate limit -> guard -> connector -> audit.

The MCP server is a thin layer over this class, which also makes it straightforward to test and benchmark.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable

import yaml

from .audit import AuditLog
from .auth import Principal
from .connectors import Connector, make_connector
from .guard import check_sql
from .ratelimit import TokenBucketLimiter
from .rest import OpenAPIService

TOOLS = ("search_tables", "describe_table", "run_readonly_query", "list_api_operations", "call_api_endpoint")


class Gateway:
    def __init__(self, config: dict, base_dir: Path | None = None, transports: dict | None = None):
        base = Path(base_dir or ".")
        self.cfg = config
        self.sources: dict[str, Connector] = {}
        for name, src in config.get("sources", {}).items():
            src = dict(src)
            if src.get("path"):
                src["path"] = str((base / src["path"]).resolve())
            self.sources[name] = make_connector(src)
        self.services: dict[str, OpenAPIService] = {}
        for name, svc in config.get("services", {}).items():
            spec = json.loads((base / svc["openapi"]).read_text(encoding="utf-8"))
            self.services[name] = OpenAPIService(name, spec, svc["base_url"], svc["allowed_operations"],
                                                 tuple(svc.get("allowed_methods", ["get"])),
                                                 transport=(transports or {}).get(name))
        lim = config.get("limits", {})
        self.row_cap = int(lim.get("row_cap", 1000))
        self.timeout_s = float(lim.get("statement_timeout_s", 10))
        self.limiter = TokenBucketLimiter(int(lim.get("burst", 20)), float(lim.get("per_second", 2)))
        self.audit = AuditLog(config.get("audit_log"))
        self.roles = config.get("roles", {})

    @classmethod
    def from_file(cls, path: str | Path, **kw) -> "Gateway":
        p = Path(path)
        return cls(yaml.safe_load(p.read_text(encoding="utf-8")), base_dir=p.parent, **kw)

    # ------------------------------------------------------------------ authorization helpers
    def _role(self, p: Principal) -> dict:
        return self.roles.get(p.role, {})

    def allowed_sources(self, p: Principal) -> list[str]:
        return [s for s in self._role(p).get("sources", []) if s in self.sources]

    def allowed_services(self, p: Principal) -> list[str]:
        return [s for s in self._role(p).get("services", []) if s in self.services]

    def _run(self, p: Principal | None, tool: str, args: dict, fn: Callable[[], dict]) -> dict:
        if p is None:
            return {"error": "Unauthenticated", "message": "missing or invalid bearer token"}
        t0 = time.perf_counter()

        def done(decision: str, out: dict, reason: str = "") -> dict:
            self.audit.write(subject=p.subject, role=p.role, tool=tool, args=args, decision=decision, reason=reason,
                             latency_ms=(time.perf_counter() - t0) * 1000, rows=out.get("row_count"))
            return out

        if tool not in self._role(p).get("tools", []):
            return done("deny", {"error": "Forbidden", "message": f"role {p.role} may not use {tool}"}, "rbac_tool")
        ok, retry = self.limiter.allow(p.subject, tool)
        if not ok:
            return done("deny", {"error": "RateLimited", "retry_after_s": round(retry, 2)}, "rate_limit")
        try:
            out = fn()
        except KeyError as e:
            return done("error", {"error": "NotFound", "message": str(e)}, "not_found")
        except Exception as e:  # driver errors, timeouts
            return done("error", {"error": type(e).__name__, "message": str(e)[:300]}, "backend_error")
        decision = "deny" if out.get("error") in ("Forbidden", "QueryRejected", "OperationNotAllowed",
                                                  "MethodNotAllowed") else "allow"
        return done(decision, out, out.get("reason", out.get("error", "")))

    def _source(self, p: Principal, source: str) -> Connector | dict:
        if source not in self.allowed_sources(p):
            return {"error": "Forbidden", "message": f"role {p.role} has no access to source '{source}'"}
        return self.sources[source]

    # ------------------------------------------------------------------ tools
    def search_tables(self, p: Principal | None, query: str) -> dict:
        def fn():
            q, hits = query.lower(), []
            for name in self.allowed_sources(p):
                for t in self.sources[name].list_tables():
                    table = ".".join(x for x in (t.get("schema"), t["table"]) if x)
                    if q in table.lower():
                        hits.append({"source": name, "table": table})
            return {"matches": hits[:50]}
        return self._run(p, "search_tables", {"query": query}, fn)

    def describe_table(self, p: Principal | None, source: str, table: str) -> dict:
        def fn():
            conn = self._source(p, source)
            return conn if isinstance(conn, dict) else conn.describe(table)
        return self._run(p, "describe_table", {"source": source, "table": table}, fn)

    def run_readonly_query(self, p: Principal | None, source: str, sql: str, limit: int = 100) -> dict:
        def fn():
            conn = self._source(p, source)
            if isinstance(conn, dict):
                return conn
            g = check_sql(sql, dialect=conn.dialect, row_cap=min(max(int(limit), 1), self.row_cap))
            if not g.allowed:
                return {"error": "QueryRejected", "reason": g.reason}
            res = conn.query(g.sql, self.timeout_s)
            return {"columns": res.columns, "rows": res.rows, "row_count": len(res.rows)}
        return self._run(p, "run_readonly_query", {"source": source, "sql": sql, "limit": limit}, fn)

    def list_api_operations(self, p: Principal | None) -> dict:
        def fn():
            return {"services": {s: self.services[s].visible_operations() for s in self.allowed_services(p)}}
        return self._run(p, "list_api_operations", {}, fn)

    def call_api_endpoint(self, p: Principal | None, service: str, operation_id: str, params: dict | None = None) -> dict:
        def fn():
            if service not in self.allowed_services(p):
                return {"error": "Forbidden", "message": f"role {p.role} has no access to service '{service}'"}
            return self.services[service].call(operation_id, params or {})
        return self._run(p, "call_api_endpoint", {"service": service, "operation_id": operation_id,
                                                  "params": params}, fn)

    def schema_document(self, p: Principal | None, source: str) -> dict:
        def fn():
            conn = self._source(p, source)
            if isinstance(conn, dict):
                return conn
            return {"source": source, "tables": [conn.describe(t["table"]) for t in conn.list_tables()]}
        return self._run(p, "describe_table", {"source": source, "resource": "schema"}, fn)
