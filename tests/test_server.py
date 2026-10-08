"""MCP layer: tool listing, annotations, and that tools act as the authenticated principal only."""
import asyncio
import json

from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser

from unified_mcp.auth import JWTVerifier, issue_dev_token
from unified_mcp.gateway import Gateway
from unified_mcp.server import build_server

AUD = "http://localhost:8000/mcp"
KEY = "test-secret-at-least-32-bytes-long!!"


def _text(result) -> dict:
    blocks = getattr(result, "content", result)
    if isinstance(blocks, tuple):
        blocks = blocks[0]
    return json.loads(blocks[0].text)


def _call_as(server, verifier, role, tool, args):
    access = asyncio.run(verifier.verify_token(issue_dev_token(KEY, "u1", role, AUD)))
    tok = auth_context_var.set(AuthenticatedUser(access))
    try:
        return _text(asyncio.run(server.call_tool(tool, args)))
    finally:
        auth_context_var.reset(tok)


def test_tools_and_annotations(demo_dir):
    server = build_server(Gateway.from_file(demo_dir / "config.yaml"), JWTVerifier(KEY, AUD), AUD)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == {"search_tables", "describe_table", "run_readonly_query", "list_api_operations",
                          "call_api_endpoint"}
    assert tools["run_readonly_query"].annotations.model_dump(by_alias=True)["readOnlyHint"] is True


def test_tool_runs_as_token_principal(demo_dir):
    v = JWTVerifier(KEY, AUD)
    server = build_server(Gateway.from_file(demo_dir / "config.yaml"), v, AUD)
    q = {"source": "hr", "sql": "SELECT count(*) AS n FROM employees"}
    assert _call_as(server, v, "hr_analyst", "run_readonly_query", q)["rows"] == [[100]]
    assert _call_as(server, v, "analyst", "run_readonly_query", q)["error"] == "Forbidden"
    # no token in context -> unauthenticated, even when calling in-process
    assert _text(asyncio.run(server.call_tool("run_readonly_query", q)))["error"] == "Unauthenticated"
