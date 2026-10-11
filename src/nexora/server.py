import json
import secrets
import time

import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from . import db
from .auth import BearerAuth
from .config import get_settings
from .guard import GuardError, classify

S = get_settings()

# Host-header check is off because requests arrive through a tunnel; bearer auth protects the endpoint.
mcp = FastMCP(
    "nexora-db",
    host=S.host,
    port=S.port,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=False)

# confirm_token -> (sql, params, expires_at)
_pending: dict[str, tuple[str, list | None, float]] = {}


def _audit(event: dict) -> None:
    event["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    with open(S.audit_log, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


@mcp.tool(annotations=READ)
async def list_tables() -> list[dict]:
    """List tables in the database with approximate row counts and sizes."""
    rows, _ = await db.fetch(
        S,
        "SELECT TABLE_NAME AS name, TABLE_ROWS AS approx_rows, "
        "ROUND((DATA_LENGTH+INDEX_LENGTH)/1024/1024,2) AS size_mb "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
        (S.db_name,),
    )
    return rows


@mcp.tool(annotations=READ)
async def describe_table(table: str) -> dict:
    """Show columns, indexes and foreign keys of a table."""
    db.check_ident(table)
    cols, _ = await db.fetch(
        S,
        "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_DEFAULT, EXTRA, COLUMN_COMMENT "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY ORDINAL_POSITION",
        (S.db_name, table),
    )
    if not cols:
        raise ValueError(f"Table {table!r} not found.")
    idx, _ = await db.fetch(
        S,
        "SELECT INDEX_NAME, NON_UNIQUE, COLUMN_NAME, SEQ_IN_INDEX FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s ORDER BY INDEX_NAME, SEQ_IN_INDEX",
        (S.db_name, table),
    )
    fks, _ = await db.fetch(
        S,
        "SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME, CONSTRAINT_NAME "
        "FROM information_schema.KEY_COLUMN_USAGE WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s "
        "AND REFERENCED_TABLE_NAME IS NOT NULL",
        (S.db_name, table),
    )
    return {"columns": cols, "indexes": idx, "foreign_keys": fks}


@mcp.tool(annotations=READ)
async def table_stats(table: str) -> dict:
    """Approximate row count, size and engine of one table."""
    db.check_ident(table)
    rows, _ = await db.fetch(
        S,
        "SELECT ENGINE, TABLE_ROWS, DATA_LENGTH, INDEX_LENGTH, AUTO_INCREMENT, UPDATE_TIME "
        "FROM information_schema.TABLES WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s",
        (S.db_name, table),
    )
    if not rows:
        raise ValueError(f"Table {table!r} not found.")
    return rows[0]


@mcp.tool(annotations=READ)
async def run_select(sql: str, params: list | None = None) -> dict:
    """Run one read-only statement (SELECT/SHOW/DESCRIBE/EXPLAIN). Use %s placeholders with `params`.
    Results are capped at the server's MAX_ROWS."""
    c = classify(sql)
    if c.kind != "read":
        raise GuardError("run_select accepts read-only statements only. Use preview_write for changes.")
    rows, truncated = await db.fetch(S, sql, params, limit=S.max_rows)
    return {"rows": rows, "row_count": len(rows), "truncated": truncated}


@mcp.tool(annotations=READ)
async def preview_write(sql: str, params: list | None = None) -> dict:
    """Dry-run one INSERT/UPDATE/DELETE/CREATE/ALTER statement (rolled back) and return a confirm_token.
    Show the user the SQL and affected rows, and call execute_write only after they approve.
    DROP/TRUNCATE/GRANT, multiple statements, and UPDATE/DELETE without WHERE are rejected."""
    c = classify(sql)
    if c.kind == "read":
        raise GuardError("Use run_select for read-only statements.")
    affected = None
    if c.kind == "write":
        affected = await db.run_write(S, sql, params, commit=False)
    now = time.time()
    for t in [t for t, (_, _, exp_at) in _pending.items() if exp_at < now]:
        del _pending[t]
    token = secrets.token_urlsafe(16)
    _pending[token] = (sql, params, now + S.confirm_ttl_seconds)
    return {
        "kind": c.kind,
        "sql": sql,
        "would_affect_rows": affected,  # None for DDL: not previewable (MySQL DDL auto-commits)
        "confirm_token": token,
        "expires_in_seconds": S.confirm_ttl_seconds,
    }


@mcp.tool(annotations=WRITE)
async def execute_write(confirm_token: str) -> dict:
    """Execute and commit a statement previously validated by preview_write. Single use."""
    item = _pending.pop(confirm_token, None)
    if item is None or item[2] < time.time():
        raise ValueError("Invalid or expired confirm_token. Call preview_write again.")
    sql, params, _ = item
    affected = await db.run_write(S, sql, params, commit=True)
    _audit({"sql": sql, "params": params, "affected": affected})
    return {"status": "committed", "affected_rows": affected}


def main() -> None:
    app = BearerAuth(mcp.streamable_http_app(), S.mcp_api_key)
    uvicorn.run(app, host=S.host, port=S.port)


if __name__ == "__main__":
    main()
