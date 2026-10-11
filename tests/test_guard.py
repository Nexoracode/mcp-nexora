import pytest

from nexora.guard import GuardError, classify


@pytest.mark.parametrize("sql,kind", [
    ("SELECT * FROM users WHERE id = 1", "read"),
    ("SHOW TABLES", "read"),
    ("DESCRIBE users", "read"),
    ("EXPLAIN SELECT 1", "read"),
    ("SELECT * FROM t WHERE id = %s", "read"),
    ("UPDATE t SET a = %s WHERE id = %s", "write"),
    ("INSERT INTO t (a) VALUES (1)", "write"),
    ("UPDATE t SET a=1 WHERE id=2", "write"),
    ("DELETE FROM t WHERE id=2", "write"),
    ("CREATE TABLE x (id INT)", "ddl"),
    ("ALTER TABLE x ADD COLUMN b INT", "ddl"),
])
def test_allowed(sql, kind):
    assert classify(sql).kind == kind


@pytest.mark.parametrize("sql", [
    "DROP TABLE t",
    "TRUNCATE TABLE t",
    "GRANT ALL ON *.* TO x",
    "UPDATE t SET a=1",
    "DELETE FROM t",
    "SELECT 1; DROP TABLE t",
    "SELECT * FROM t INTO OUTFILE '/tmp/x'",
    "not sql at all (((",
])
def test_rejected(sql):
    with pytest.raises(GuardError):
        classify(sql)
