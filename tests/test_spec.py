"""按 docs/SQL_SPEC.md 逐条编写的验收测试。

这些测试覆盖当前引擎缺失的写法：AND/OR/括号、IS NULL、ORDER BY、
聚合与 GROUP BY、JOIN、LIMIT/OFFSET，以及不支持语法必须抛 QueryError。
"""

import pytest

from engine.data import QueryError
from engine.query import query


# --- 规范第 2 条：WHERE 的 AND / OR / 括号 / IS NULL -----------------------

def test_where_and():
    rows = query("SELECT name FROM users WHERE city = 'Beijing' AND age > 35")
    assert [r["name"] for r in rows] == ["Carol", "Frank"]


def test_where_or():
    rows = query("SELECT name FROM users WHERE city = 'Shenzhen' OR age = 23")
    assert [r["name"] for r in rows] == ["Dave", "Eve"]


def test_where_parentheses_change_precedence():
    # 括号先算 OR：Beijing 3 人 + Shanghai 2 人，再筛 age >= 30
    # Bob(28)/Eve(23) 被过滤，剩 Beijing 的 Alice/Carol/Frank
    rows = query(
        "SELECT name FROM users "
        "WHERE (city = 'Beijing' OR city = 'Shanghai') AND age >= 30"
    )
    assert [r["name"] for r in rows] == ["Alice", "Carol", "Frank"]


def test_where_or_without_parentheses_uses_or_precedence():
    # AND 优先级高于 OR：条件等价于 city='Beijing' OR (city='Shanghai' AND age=23)
    # 命中 Beijing 三人加上海的 Eve；按 CSV 原顺序返回
    rows = query(
        "SELECT name FROM users "
        "WHERE city = 'Beijing' OR city = 'Shanghai' AND age = 23"
    )
    assert {r["name"] for r in rows} == {"Alice", "Carol", "Frank", "Eve"}


def test_where_is_null():
    rows = query("SELECT name FROM users WHERE manager_id IS NULL")
    assert [r["name"] for r in rows] == ["Alice"]


def test_where_is_not_null():
    rows = query("SELECT name FROM users WHERE manager_id IS NOT NULL")
    assert len(rows) == 5


def test_null_compare_not_treated_as_zero():
    # Dave 的 age 为 NULL，NULL 不等于 0，也不满足 <= 23
    rows = query("SELECT name FROM users WHERE age <= 23")
    assert [r["name"] for r in rows] == ["Eve"]
    rows = query("SELECT name FROM users WHERE age = 0")
    assert rows == []


# --- 规范第 3 条：ORDER BY ------------------------------------------------

def test_order_by_single_column_desc():
    rows = query("SELECT name, age FROM users ORDER BY age DESC")
    assert [r["name"] for r in rows] == ["Carol", "Frank", "Alice", "Bob", "Eve", "Dave"]


def test_order_by_multi_columns():
    rows = query("SELECT name, city, age FROM users ORDER BY city ASC, age DESC")
    cities = [r["city"] for r in rows]
    assert cities == sorted(cities)
    # Beijing 组内按 age 降序
    beijing_ages = [r["age"] for r in rows if r["city"] == "Beijing"]
    assert beijing_ages == ["41", "37", "34"]
    # NULL age 的 Dave 排在 Shenzhen 组末尾（NULL 视为最小）
    assert rows[-1]["name"] == "Dave"


# --- 规范第 4 条：聚合与分组 ----------------------------------------------

def test_group_by_count():
    rows = query("SELECT city, COUNT(*) AS cnt FROM users GROUP BY city")
    counts = {r["city"]: r["cnt"] for r in rows}
    assert counts == {"Beijing": 3, "Shanghai": 2, "Shenzhen": 1}


def test_group_by_sum():
    rows = query("SELECT status, SUM(amount) AS total FROM orders GROUP BY status")
    totals = {r["status"]: r["total"] for r in rows}
    # paid: 1200 + 450 + 3000，第 106 单 amount 为 NULL 被忽略
    assert totals == {"paid": 4650, "pending": 800, "refunded": 120}


def test_aggregate_without_group_by_is_whole_table():
    rows = query("SELECT AVG(age) AS avg_age FROM users")
    assert len(rows) == 1
    # 5 个非 NULL age: 34+28+41+23+37 = 163
    assert rows[0]["avg_age"] == pytest.approx(163 / 5)


def test_count_star_vs_count_column():
    star = query("SELECT COUNT(*) AS c FROM orders")[0]["c"]
    col = query("SELECT COUNT(amount) AS c FROM orders")[0]["c"]
    assert star == 6
    assert col == 5  # 第 106 单 amount 为 NULL


def test_min_max_ignore_null():
    row = query("SELECT MIN(age) AS lo, MAX(age) AS hi FROM users")[0]
    assert row["lo"] == 23
    assert row["hi"] == 41


def test_group_by_multiple_rows_order_preserved():
    rows = query("SELECT city, COUNT(*) AS cnt FROM users GROUP BY city")
    # 分组按首次出现顺序输出：Beijing, Shanghai, Shenzhen
    assert [r["city"] for r in rows] == ["Beijing", "Shanghai", "Shenzhen"]


# --- 规范第 5 条：INNER JOIN ----------------------------------------------

def test_inner_join_with_aliases():
    rows = query(
        "SELECT u.name, o.amount FROM users u "
        "JOIN orders o ON u.id = o.user_id"
    )
    # 6 张订单都能匹配到用户
    assert len(rows) == 6
    first = rows[0]
    assert set(first) == {"name", "amount"}
    assert first["name"] == "Alice"
    assert first["amount"] == "1200"


def test_join_qualified_column_names():
    rows = query(
        "SELECT u.name, o.status FROM users u "
        "INNER JOIN orders o ON u.id = o.user_id WHERE o.status = 'paid'"
    )
    # paid 订单 4 张：Alice 两张、Carol 一张、Bob 一张（第 106 单金额为 NULL 但状态是 paid）
    assert len(rows) == 4
    assert {r["name"] for r in rows} == {"Alice", "Carol", "Bob"}


# --- 规范第 6 条：LIMIT / OFFSET ------------------------------------------

def test_limit():
    rows = query("SELECT id FROM users ORDER BY id ASC LIMIT 2")
    assert [r["id"] for r in rows] == ["1", "2"]


def test_limit_offset():
    rows = query("SELECT id FROM users ORDER BY id ASC LIMIT 2 OFFSET 2")
    assert [r["id"] for r in rows] == ["3", "4"]


def test_limit_beyond_table_size():
    rows = query("SELECT id FROM users LIMIT 100")
    assert len(rows) == 6


# --- 规范第 1 / 7 条：大小写不敏感、字面量与错误处理 ------------------------

def test_column_and_keyword_case_insensitive():
    rows = query("select NAME from users where CITY = 'Beijing'")
    assert len(rows) == 3
    # 输出列名统一小写
    assert set(rows[0]) == {"name"}


def test_unsupported_syntax_raises_query_error():
    with pytest.raises(QueryError):
        query("SELECT * FROM users GROUP BY city TYPO")
    with pytest.raises(QueryError):
        query("SELECT * FROM users WHERE")
    with pytest.raises(QueryError):
        query("SELECT * FROM users LIMIT -1")
    with pytest.raises(QueryError):
        query("UPDATE users SET age = 1")
