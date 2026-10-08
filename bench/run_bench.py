"""Reproducible measurements for the README.

    python scripts/make_demo_data.py && python -m bench.run_bench

1. Red-team: block rate on attack queries, false-positive rate on benign analyst queries (guard only).
2. Latency: end-to-end Gateway.run_readonly_query (RBAC + rate limit + guard + SQLite query + audit), in-process.
   No network hop, so this measures server overhead plus query time and is NOT a deployed-latency number.
3. Context cost: tokens in this server's tools/list payload vs a naive "one tool per table" design over the same
   14 tables. Counted with tiktoken's cl100k_base as a model-agnostic approximation (Claude's tokenizer differs).
"""
from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections import Counter
from pathlib import Path

import yaml

from unified_mcp.auth import Principal
from unified_mcp.gateway import Gateway
from unified_mcp.guard import check_sql
from unified_mcp.server import build_server

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "bench" / "reports"


def redteam() -> dict:
    cases = yaml.safe_load((ROOT / "tests" / "security" / "redteam_cases.yaml").read_text(encoding="utf-8"))
    blocked = [c for c in cases["attacks"] if not check_sql(c["sql"], c["dialect"]).allowed]
    fps = [c for c in cases["benign"] if not check_sql(c["sql"], c["dialect"]).allowed]
    by_cat = Counter(c["category"] for c in cases["attacks"])
    return {"attacks": len(cases["attacks"]), "blocked": len(blocked), "benign": len(cases["benign"]),
            "false_positives": len(fps), "categories": dict(by_cat)}


def latency(n: int = 2000) -> dict:
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["audit_log"] = None
    cfg["limits"]["burst"], cfg["limits"]["per_second"] = 10**9, 10**9  # measure the path, not the limiter
    gw = Gateway(cfg, base_dir=ROOT)
    p = Principal("bench", "analyst")
    queries = [
        "SELECT count(*) FROM orders WHERE status = 'shipped'",
        "SELECT c.country, sum(o.total) FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.country",
        "SELECT * FROM products WHERE category = 'books' ORDER BY price DESC",
        "SELECT p.category, avg(r.rating) FROM reviews r JOIN products p ON p.id = r.product_id GROUP BY 1",
    ]
    samples = []
    for i in range(n):
        t0 = time.perf_counter()
        out = gw.run_readonly_query(p, "shop", queries[i % len(queries)], limit=100)
        samples.append((time.perf_counter() - t0) * 1000)
        assert "error" not in out, out
    q = statistics.quantiles(samples, n=100)
    guard = [(lambda t0: (check_sql(queries[i % 4], "sqlite"), (time.perf_counter() - t0) * 1000)[1])(time.perf_counter())
             for i in range(n)]
    return {"calls": n, "p50_ms": round(q[49], 2), "p95_ms": round(q[94], 2),
            "guard_only_p50_ms": round(statistics.median(guard), 3), "backend": "SQLite (in-process)"}


def context_cost() -> dict:
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    cfg["audit_log"] = None
    gw = Gateway(cfg, base_dir=ROOT)
    tools = asyncio.run(build_server(gw).list_tools())
    ours = json.dumps([t.model_dump(by_alias=True, exclude_none=True) for t in tools])
    naive = []
    for src, conn in gw.sources.items():
        for t in conn.list_tables():
            d = conn.describe(t["table"])
            cols = ", ".join(f"{c['name']} {c['type']}" for c in d["columns"])
            naive.append({"name": f"query_{src}_{t['table']}",
                          "description": f"Query the {t['table']} table in {src}. Columns: {cols}.",
                          "inputSchema": {"type": "object", "properties": {
                              "columns": {"type": "array", "items": {"type": "string"}},
                              "where": {"type": "string"}, "order_by": {"type": "string"},
                              "limit": {"type": "integer"}}}})
    naive_s = json.dumps(naive)
    return {"tables": len(naive), "this_server_tools": len(tools), "this_server_tokens": len(enc.encode(ours)),
            "naive_tools": len(naive), "naive_tokens": len(enc.encode(naive_s)), "tokenizer": "cl100k_base"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    res = {"redteam": redteam(), "latency": latency(), "context_cost": context_cost()}
    (OUT / "results.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    r, lt, c = res["redteam"], res["latency"], res["context_cost"]
    md = f"""| Metric | Result |
|---|---|
| Red-team attacks blocked by the SQL guard | **{r['blocked']}/{r['attacks']}** across {len(r['categories'])} categories |
| Benign analyst queries wrongly rejected | **{r['false_positives']}/{r['benign']}** |
| Tool latency, end-to-end in-process (SQLite), {lt['calls']} calls | P50 {lt['p50_ms']} ms · P95 {lt['p95_ms']} ms |
| SQL guard alone (parse + AST checks) | P50 {lt['guard_only_p50_ms']} ms |
| `tools/list` size: this server vs one-tool-per-table ({c['tables']} tables) | {c['this_server_tools']} tools / **{c['this_server_tokens']} tokens** vs {c['naive_tools']} tools / {c['naive_tokens']} tokens ({c['tokenizer']}) |
"""
    (OUT / "summary.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
