# mini-sql

一个玩具级 SQL 查询引擎，给内部报表工具做本地查询用。

## 技术栈

- Python 3.12，纯标准库

## 用法

```python
from engine.query import query

rows = query("SELECT name, age FROM users WHERE age > 30")
```

## 目录

```
engine/query.py    查询入口（目前所有逻辑都在这一个文件里）
data/              users / orders 两张表
docs/SQL_SPEC.md   支持的语法
tests/             29 个用例
```

## 测试

```bash
.venv/Scripts/python -m pytest -q
```

## 已知问题

- `engine/query.py` 已经 488 行，解析、规划、求值全揉在一起，改一处很容易碰坏别处。
- 想加新语法（比如子查询）根本没地方下手。
