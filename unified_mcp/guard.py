"""SQL guard: parse the query into an AST and accept only a single read-only SELECT.

This is defence in depth. The real safety net is that every connector runs on a read-only
connection/role with a statement timeout. The guard exists so that destructive or dangerous SQL is
rejected *before* it reaches a database, with a reason the agent can act on.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# sqlglot logs a warning when it falls back to a generic Command node; that node is rejected below anyway.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

# Node types that must never appear anywhere in the tree (looked up by name so sqlglot version drift is safe).
_FORBIDDEN_NAMES = [
    "Insert", "Update", "Delete", "Drop", "Create", "Alter", "AlterTable", "Merge", "TruncateTable",
    "Command", "Into", "Copy", "Set", "Transaction", "Commit", "Rollback", "Use", "Pragma", "LoadData",
    "Lock", "Grant", "Revoke", "Comment", "Attach", "Detach", "Put", "Call", "Execute", "Prepare",
]
FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NAMES if hasattr(exp, n))
ALLOWED_ROOTS = tuple(getattr(exp, n) for n in ("Select", "Union", "Intersect", "Except", "SetOperation")
                      if hasattr(exp, n))

DENY_FUNCTIONS = {
    "pg_sleep", "sleep", "benchmark", "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "lo_import", "lo_export", "dblink", "dblink_exec", "pg_terminate_backend", "pg_cancel_backend",
    "set_config", "load_extension", "readfile", "writefile", "pg_reload_conf", "pg_rotate_logfile",
    "system$cancel_all_queries", "system$abort_session", "system$wait",
}
DENY_TABLES = {"pg_authid", "pg_shadow", "pg_user_mapping", "pg_user_mappings", "pg_largeobject"}


@dataclass
class GuardResult:
    allowed: bool
    reason: str = ""
    sql: str = ""  # normalized SQL with the row cap applied (only when allowed)


def _func_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def check_sql(sql: str, dialect: str = "postgres", row_cap: int = 1000) -> GuardResult:
    try:
        statements = [s for s in sqlglot.parse(sql, read=dialect) if s is not None]
    except ParseError as e:
        return GuardResult(False, f"parse error: {str(e).splitlines()[0]}")
    if len(statements) != 1:
        return GuardResult(False, f"exactly one statement allowed, got {len(statements)}")
    tree = statements[0]
    if not isinstance(tree, ALLOWED_ROOTS):
        return GuardResult(False, f"only SELECT queries are allowed (got {type(tree).__name__})")
    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            return GuardResult(False, f"forbidden operation: {type(node).__name__}")
        if isinstance(node, exp.Func) and _func_name(node) in DENY_FUNCTIONS:
            return GuardResult(False, f"forbidden function: {_func_name(node)}")
        if isinstance(node, exp.Table) and node.name.lower() in DENY_TABLES:
            return GuardResult(False, f"forbidden table: {node.name}")
    inner = tree.sql(dialect=dialect)
    capped = f"SELECT * FROM ({inner}) AS _mcp_q LIMIT {int(row_cap)}"
    return GuardResult(True, sql=capped)
