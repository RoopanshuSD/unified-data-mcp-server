"""MCP server: a thin transport layer over Gateway.

    MCP_JWT_SECRET=dev-secret python -m unified_mcp.server --config config.yaml   # Streamable HTTP on :8000/mcp

Authentication follows the MCP authorization model for remote servers: the server is an OAuth 2.1 *resource
server*. The SDK's bearer middleware calls JWTVerifier for every request, and each tool reads the verified
principal from the request context. Requests without a valid token never reach a tool.
"""
from __future__ import annotations

import argparse
import json
import os

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.types import ToolAnnotations

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import MCPServer
except ImportError:  # 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from .auth import JWTVerifier, principal_from
from .gateway import Gateway

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)


def _j(x: dict) -> str:
    return json.dumps(x, default=str)


def build_server(gw: Gateway, verifier: JWTVerifier | None = None, resource_url: str = "http://localhost:8000/mcp",
                 issuer_url: str = "https://auth.example.com") -> MCPServer:
    kw = {}
    if verifier is not None:
        kw = dict(token_verifier=verifier,
                  auth=AuthSettings(issuer_url=issuer_url, resource_server_url=resource_url, required_scopes=[],
                                   validate_token_resource=False))  # JWTVerifier checks `aud` itself
    mcp = MCPServer("unified-data", instructions=(
        "Read-only access to company data. Start with search_tables, then describe_table or read the "
        "schema://{source} resource, then run_readonly_query. Only single SELECT statements are accepted."), **kw)

    def me():
        return principal_from(get_access_token())

    @mcp.tool(annotations=READ_ONLY)
    def search_tables(query: str) -> str:
        """Find tables whose name contains `query` across the data sources you can access."""
        return _j(gw.search_tables(me(), query))

    @mcp.tool(annotations=READ_ONLY)
    def describe_table(source: str, table: str) -> str:
        """Columns, types, keys and row count for one table."""
        return _j(gw.describe_table(me(), source, table))

    @mcp.tool(annotations=READ_ONLY)
    def run_readonly_query(source: str, sql: str, limit: int = 100) -> str:
        """Run ONE read-only SELECT on a source. Rows are capped by `limit` and the server row cap."""
        return _j(gw.run_readonly_query(me(), source, sql, limit))

    @mcp.tool(annotations=READ_ONLY)
    def list_api_operations() -> str:
        """REST operations (from OpenAPI specs) you are allowed to call."""
        return _j(gw.list_api_operations(me()))

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    def call_api_endpoint(service: str, operation_id: str, params: dict | None = None) -> str:
        """Call an allow-listed REST operation by operationId with path/query params."""
        return _j(gw.call_api_endpoint(me(), service, operation_id, params))

    @mcp.resource("schema://{source}", mime_type="application/json")
    def schema(source: str) -> str:
        """Full schema documentation for a source, fetched on demand instead of living in the prompt."""
        return _j(gw.schema_document(me(), source))

    return mcp


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--resource-url", default=os.environ.get("MCP_RESOURCE_URL", "http://localhost:8000/mcp"))
    args = ap.parse_args()
    key = os.environ.get("MCP_JWT_PUBLIC_KEY") or os.environ.get("MCP_JWT_SECRET")
    if not key:
        raise SystemExit("Set MCP_JWT_SECRET (dev, HS256) or MCP_JWT_PUBLIC_KEY (RS256).")
    gw = Gateway.from_file(args.config)
    build_server(gw, JWTVerifier(key, audience=args.resource_url), args.resource_url).run(transport="streamable-http")


if __name__ == "__main__":
    main()
