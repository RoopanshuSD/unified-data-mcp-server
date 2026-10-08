"""Print a dev JWT for a role:  python scripts/dev_token.py analyst"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from unified_mcp.auth import issue_dev_token  # noqa: E402

role = sys.argv[1] if len(sys.argv) > 1 else "analyst"
print(issue_dev_token(os.environ["MCP_JWT_SECRET"], sub=f"dev-{role}", role=role,
                      audience=os.environ.get("MCP_RESOURCE_URL", "http://localhost:8000/mcp")))
