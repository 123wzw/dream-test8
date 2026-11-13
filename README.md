# mini-sql

一个玩具级 SQL 查询引擎，给内部报表工具做本地查询用。

## 技术栈

- Python 3.12，纯标准库

## 用法

```python
from engine.query import query

rows = query("SELECT name, age FROM users WHERE age > 30")
```

数据从 `data/` 下的 CSV 加载，表名即文件名。

## 数据

| 文件 | 内容 |
|---|---|
| `data/users.csv` | id, name, age, city, manager_id |
| `data/orders.csv` | id, user_id, amount, status, created_at |

## 支持的语法

见 `docs/SQL_SPEC.md`，里面列的写法都要支持。

## 测试

```bash
.venv/Scripts/python -m pytest -q
```

## 已知问题

- 目前只够跑最简单的单表查询，报表那边提的需求大半还不支持。
- `JOIN`、聚合、排序都还没有。
