"""Classify a single SQL statement as read / write / ddl or reject it."""
from dataclasses import dataclass

import sqlglot
from sqlglot import exp


class GuardError(ValueError):
    pass


@dataclass(frozen=True)
class Classified:
    kind: str  # "read" | "write" | "ddl"
    statement: str


_READ_ROOTS = (exp.Select, exp.Show, exp.Describe, exp.Union, exp.Subquery)
_DDL_ROOTS = tuple(getattr(exp, n) for n in ("Create", "Alter", "AlterTable") if hasattr(exp, n))
_FORBIDDEN = (exp.Drop, exp.TruncateTable, exp.Grant)


def _parse_one(sql: str) -> exp.Expression:
    try:
        parsed = [p for p in sqlglot.parse(sql, read="mysql") if p is not None]
    except sqlglot.errors.SqlglotError as e:
        raise GuardError(f"SQL parse error: {e}") from e
    if len(parsed) != 1:
        raise GuardError("Exactly one SQL statement is allowed.")
    return parsed[0]


def classify(sql: str) -> Classified:
    node = _parse_one(sql)

    if isinstance(node, _FORBIDDEN) or node.find(*_FORBIDDEN):
        raise GuardError("DROP / TRUNCATE / GRANT statements are not allowed.")

    if isinstance(node, _READ_ROOTS):
        if node.find(exp.Into):  # SELECT ... INTO OUTFILE
            raise GuardError("SELECT INTO is not allowed.")
        return Classified("read", sql)

    if isinstance(node, (exp.Update, exp.Delete)):
        if node.args.get("where") is None:
            raise GuardError(f"{type(node).__name__.upper()} without WHERE is not allowed.")
        return Classified("write", sql)

    if isinstance(node, exp.Insert):
        return Classified("write", sql)

    if isinstance(node, _DDL_ROOTS):
        return Classified("ddl", sql)

    raise GuardError(f"Statement type {type(node).__name__} is not allowed.")
