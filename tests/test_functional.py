"""查询引擎功能测试。"""

import pytest

from engine.data import QueryError
from engine.query import query


def test_select_all():
    rows = query("SELECT * FROM users")
    assert len(rows) == 6
    assert rows[0]["id"] == "1"


def test_select_columns():
    rows = query("SELECT name, age FROM users")
    assert set(rows[0]) == {"name", "age"}


def test_where_numeric_comparison():
    rows = query("SELECT name FROM users WHERE age > 30")
    assert len(rows) == 3


def test_where_string_comparison():
    rows = query("SELECT name FROM users WHERE city = 'Beijing'")
    assert len(rows) == 3


def test_where_no_match():
    assert query("SELECT * FROM users WHERE city = 'Mars'") == []


def test_unknown_table_raises():
    with pytest.raises(QueryError):
        query("SELECT * FROM nope")


def test_non_select_rejected():
    with pytest.raises(QueryError):
        query("DELETE FROM users")
