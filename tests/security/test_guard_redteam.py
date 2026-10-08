from pathlib import Path

import pytest
import yaml

from unified_mcp.guard import check_sql

CASES = yaml.safe_load((Path(__file__).parent / "redteam_cases.yaml").read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", CASES["attacks"], ids=lambda c: c["category"] + ":" + c["sql"][:40])
def test_attack_is_blocked(case):
    r = check_sql(case["sql"], case["dialect"])
    assert not r.allowed, f"guard let through: {case['sql']}"
    assert r.reason


@pytest.mark.parametrize("case", CASES["benign"], ids=lambda c: c["sql"][:50])
def test_benign_query_is_allowed(case):
    r = check_sql(case["sql"], case["dialect"])
    assert r.allowed, r.reason


def test_row_cap_wraps_query():
    r = check_sql("SELECT * FROM orders LIMIT 100000", "postgres", row_cap=50)
    assert r.allowed and r.sql.endswith("LIMIT 50")
