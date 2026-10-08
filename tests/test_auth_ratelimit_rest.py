import asyncio
import json
import time
from pathlib import Path

import httpx

from unified_mcp.auth import JWTVerifier, issue_dev_token
from unified_mcp.ratelimit import TokenBucketLimiter
from unified_mcp.rest import OpenAPIService

AUD = "http://localhost:8000/mcp"


def test_jwt_valid_expired_wrong_audience_wrong_key():
    v = JWTVerifier("test-secret-at-least-32-bytes-long!!", audience=AUD)
    ok = asyncio.run(v.verify_token(issue_dev_token("test-secret-at-least-32-bytes-long!!", "ana", "analyst", AUD)))
    assert ok and ok.claims["role"] == "analyst" and ok.subject == "ana"
    assert asyncio.run(v.verify_token(issue_dev_token("test-secret-at-least-32-bytes-long!!", "ana", "analyst", AUD, ttl_s=-10))) is None
    assert asyncio.run(v.verify_token(issue_dev_token("test-secret-at-least-32-bytes-long!!", "ana", "analyst", "http://other"))) is None
    assert asyncio.run(v.verify_token(issue_dev_token("another-secret-also-32-bytes-long!!", "ana", "analyst", AUD))) is None
    assert asyncio.run(v.verify_token("not-a-jwt")) is None


def test_token_bucket_refills():
    t = [0.0]
    lim = TokenBucketLimiter(capacity=2, refill_per_s=1.0, clock=lambda: t[0])
    assert lim.allow("u", "q")[0] and lim.allow("u", "q")[0]
    allowed, retry = lim.allow("u", "q")
    assert not allowed and retry > 0
    t[0] += 1.0
    assert lim.allow("u", "q")[0]


def _service():
    spec = json.loads((Path(__file__).parent.parent / "specs" / "catalog.json").read_text())

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/products/7":
            return httpx.Response(200, json={"id": 7, "name": "Product 7"})
        if req.url.path == "/products":
            return httpx.Response(200, json=[{"id": 1, "category": req.url.params.get("category")}])
        return httpx.Response(404, json={})
    return OpenAPIService("catalog", spec, "http://catalog", ["listProducts", "getProduct", "deleteProduct"],
                          ("get",), transport=httpx.MockTransport(handler))


def test_rest_allow_list_and_methods():
    svc = _service()
    assert svc.call("getProduct", {"id": 7}) == {"status": 200, "body": {"id": 7, "name": "Product 7"}}
    assert svc.call("listProducts", {"category": "books"})["body"][0]["category"] == "books"
    assert svc.call("createProduct", {})["error"] == "OperationNotAllowed"
    assert svc.call("deleteProduct", {"id": 7})["error"] == "MethodNotAllowed"  # allow-listed id, but DELETE disabled
    assert svc.call("getProduct", {})["error"] == "MissingPathParameter"
    assert svc.call("listProducts", {"admin": True})["error"] == "UnknownParameters"
    assert {o["operation_id"] for o in svc.visible_operations()} == {"listProducts", "getProduct"}
