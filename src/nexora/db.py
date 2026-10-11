import re

import aiomysql
import pymysql.err

from .config import Settings

import ssl

_pool: aiomysql.Pool | None = None
_IDENT = re.compile(r"^[A-Za-z0-9_$]{1,64}$")


async def init_pool(s: Settings) -> aiomysql.Pool:
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=s.db_host, port=s.db_port, user=s.db_user, password=s.db_password,
            db=s.db_name, minsize=1, maxsize=s.db_pool_max, autocommit=False,
            cursorclass=aiomysql.DictCursor, connect_timeout=10,
            ssl=ssl.create_default_context() if s.db_ssl else None,
        )
    return _pool


def check_ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Invalid identifier: {name!r}")
    return name


def jsonable(rows):
    return [
        {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v)) for k, v in r.items()}
        for r in rows
    ]


async def fetch(s: Settings, sql: str, params=None, *, limit: int | None = None):
    """Run a read statement inside a READ ONLY transaction. Returns (rows, truncated)."""
    pool = await init_pool(s)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("START TRANSACTION READ ONLY")
            try:
                await cur.execute(sql, params)
                if limit:
                    rows = await cur.fetchmany(limit + 1)
                    truncated = len(rows) > limit
                    rows = rows[:limit]
                else:
                    rows, truncated = await cur.fetchall(), False
                return jsonable(rows), truncated
            finally:
                await conn.rollback()


TOKEN_TABLE = "_mcp_used_tokens"
_token_table_ready = False


class TokenAlreadyUsed(Exception):
    pass


async def _ensure_token_table(pool) -> None:
    global _token_table_ready
    if _token_table_ready:
        return
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"CREATE TABLE IF NOT EXISTS {TOKEN_TABLE} ("
                "token_hash CHAR(64) NOT NULL PRIMARY KEY, "
                "used_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            await conn.commit()
    _token_table_ready = True


async def run_write(s: Settings, sql: str, params=None, *, commit: bool, token_hash: str | None = None):
    """Execute a write; roll back when commit=False (preview). Returns affected rows.

    With `token_hash`, the token is recorded in the same transaction as the write, so a
    confirm token can be consumed only once across all serverless instances. If the write
    fails the transaction rolls back and the token stays usable.
    """
    pool = await init_pool(s)
    if token_hash:
        await _ensure_token_table(pool)
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                if token_hash:
                    await cur.execute(f"DELETE FROM {TOKEN_TABLE} WHERE used_at < NOW() - INTERVAL 1 DAY")
                    try:
                        await cur.execute(f"INSERT INTO {TOKEN_TABLE} (token_hash) VALUES (%s)", (token_hash,))
                    except pymysql.err.IntegrityError as e:
                        raise TokenAlreadyUsed from e
                await cur.execute(sql, params)
                affected = cur.rowcount
                if commit:
                    await conn.commit()
                else:
                    await conn.rollback()
                return affected
            except Exception:
                await conn.rollback()
                raise
