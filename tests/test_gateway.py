from pathlib import Path

import pytest
import yaml

from unified_mcp.auth import Principal
from unified_mcp.gateway import Gateway

ANALYST, HR, VIEWER = Principal("ana", "analyst"), Principal("hira", "hr_analyst"), Principal("vik", "viewer")
BENIGN_SQLITE = [c["sql"] for c in yaml.safe_load(
    (Path(__file__).parent / "security" / "redteam_cases.yaml").read_text(encoding="utf-8"))["benign"]
    if c["dialect"] == "sqlite"]


@pytest.fixture()
def gw(demo_dir):
    return Gateway.from_file(demo_dir / "config.yaml")


@pytest.mark.parametrize("sql", BENIGN_SQLITE, ids=lambda s: s[:40])
def test_benign_queries_execute_on_demo_db(gw, sql):
    out = gw.run_readonly_query(ANALYST, "shop", sql, limit=20)
    assert "error" not in out, out
    assert out["row_count"] <= 20


def test_destructive_query_rejected_and_audited(gw):
    out = gw.run_readonly_query(ANALYST, "shop", "SELECT 1; DROP TABLE customers")
    assert out["error"] == "QueryRejected"
    assert gw.audit.records[-1]["decision"] == "deny"
    assert gw.run_readonly_query(ANALYST, "shop", "SELECT count(*) AS n FROM customers")["rows"] == [[500]]


def test_rbac_sources_and_tools(gw):
    assert gw.run_readonly_query(ANALYST, "hr", "SELECT * FROM salaries")["error"] == "Forbidden"
    assert gw.run_readonly_query(HR, "hr", "SELECT count(*) FROM salaries")["rows"] == [[100]]
    assert gw.run_readonly_query(VIEWER, "shop", "SELECT 1")["error"] == "Forbidden"
    assert {m["table"] for m in gw.search_tables(ANALYST, "sal")["matches"]} == set()
    assert {m["table"] for m in gw.search_tables(HR, "sal")["matches"]} == {"salaries"}


def test_unauthenticated_is_rejected(gw):
    assert gw.run_readonly_query(None, "shop", "SELECT 1")["error"] == "Unauthenticated"


def test_describe_table_reports_foreign_keys(gw):
    d = gw.describe_table(ANALYST, "shop", "order_items")
    assert {"column": "order_id", "references": "orders.id"} in d["foreign_keys"]
    assert gw.describe_table(ANALYST, "shop", "nope")["error"] == "NotFound"


def test_rate_limit_per_user_and_tool(gw):
    outs = [gw.search_tables(ANALYST, "x") for _ in range(25)]
    limited = [o for o in outs if o.get("error") == "RateLimited"]
    assert limited and limited[0]["retry_after_s"] > 0
    assert "error" not in gw.search_tables(HR, "x")  # other users unaffected


def test_audit_hashes_arguments(gw):
    gw.run_readonly_query(ANALYST, "shop", "SELECT email FROM customers WHERE email = 'c1@example.com'")
    rec = gw.audit.records[-1]
    assert len(rec["args_sha256"]) == 64 and "c1@example.com" not in str(rec)
