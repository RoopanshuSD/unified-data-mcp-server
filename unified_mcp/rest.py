"""REST connector driven by an OpenAPI spec. Only allow-listed operationIds and HTTP methods can be called."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import httpx


@dataclass
class Operation:
    operation_id: str
    method: str
    path: str
    summary: str = ""
    params: list[str] = field(default_factory=list)


class OpenAPIService:
    def __init__(self, name: str, spec: dict, base_url: str, allowed_operations: list[str],
                 allowed_methods: tuple[str, ...] = ("get",), transport: httpx.BaseTransport | None = None,
                 timeout_s: float = 10.0, max_body_chars: int = 20_000):
        self.name, self.spec, self.base_url = name, spec, base_url
        self.allowed_ops, self.allowed_methods = set(allowed_operations), {m.lower() for m in allowed_methods}
        self.client = httpx.Client(base_url=base_url, transport=transport, timeout=timeout_s)
        self.max_body_chars = max_body_chars
        self.operations: dict[str, Operation] = {}
        for path, item in spec.get("paths", {}).items():
            for method, op in item.items():
                if "operationId" in op:
                    self.operations[op["operationId"]] = Operation(
                        op["operationId"], method.lower(), path, op.get("summary", ""),
                        [p["name"] for p in op.get("parameters", [])])

    def visible_operations(self) -> list[dict]:
        return [{"operation_id": o.operation_id, "method": o.method.upper(), "path": o.path, "summary": o.summary,
                 "params": o.params}
                for o in self.operations.values()
                if o.operation_id in self.allowed_ops and o.method in self.allowed_methods]

    def call(self, operation_id: str, params: dict) -> dict:
        op = self.operations.get(operation_id)
        if op is None:
            return {"error": "UnknownOperation", "message": operation_id}
        if operation_id not in self.allowed_ops:
            return {"error": "OperationNotAllowed", "message": f"{operation_id} is not on the allow-list"}
        if op.method not in self.allowed_methods:
            return {"error": "MethodNotAllowed", "message": f"{op.method.upper()} operations are disabled"}
        params = dict(params or {})
        path = op.path
        for name in re.findall(r"{(\w+)}", op.path):
            if name not in params:
                return {"error": "MissingPathParameter", "message": name}
            path = path.replace("{" + name + "}", httpx.URL(str(params.pop(name))).raw_path.decode().lstrip("/"))
        unknown = set(params) - set(op.params)
        if unknown:
            return {"error": "UnknownParameters", "message": sorted(unknown)}
        resp = self.client.request(op.method.upper(), path, params=params)
        try:
            body = resp.json()
        except json.JSONDecodeError:
            body = resp.text[: self.max_body_chars]
        text = json.dumps(body, default=str)
        if len(text) > self.max_body_chars:
            body = {"truncated": True, "preview": text[: self.max_body_chars]}
        return {"status": resp.status_code, "body": body}
