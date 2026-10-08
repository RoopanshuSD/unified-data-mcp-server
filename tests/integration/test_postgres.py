"""Runs only when DATABASE_URL points at a Postgres you can read (docker compose up -d)."""
import os

import pytest

from unified_mcp.connectors import PostgresConnector
from unified_mcp.guard import check_sql

pytestmark = pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")


def test_session_is_read_only_even_if_guard_were_bypassed():
    conn = PostgresConnector(os.environ["DATABASE_URL"])
    with pytest.raises(Exception, match="read-only"):
        conn.query("CREATE TABLE should_fail (id int)", timeout_s=5)  # deliberately skips the guard


def test_guarded_select_runs():
    g = check_sql("SELECT 1 AS one", "postgres", row_cap=10)
    assert PostgresConnector(os.environ["DATABASE_URL"]).query(g.sql, timeout_s=5).rows == [[1]]
