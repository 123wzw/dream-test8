# 重构要求（REFACTOR_SPEC）

目标：把 `engine/query.py` 拆成三层，**行为一个字都不能变**。

## 1. 分层

拆成至少三个模块，职责如下：

| 模块 | 职责 |
|---|---|
| `engine/parser.py` | 词法分析 + 语法分析，产出语法树；不执行、不碰数据 |
| `engine/planner.py` | 把语法树变成执行计划（决定 JOIN 顺序、过滤下推、聚合位置） |
| `engine/executor.py` | 按计划求值，返回 `list[dict]` |

- `engine/query.py` 保留为对外入口，只做串联，不再包含解析或求值逻辑。
- 每个文件不超过 **200 行**。

## 2. 行为不变

- `from engine.query import query` 的导入路径与函数签名不变。
- 返回结构与之前完全一致：`list[dict]`，键为小写列名。
- 下列 13 种查询的结果（行数、列、顺序、取值）必须与重构前逐条一致：
  1. `SELECT * FROM users`
  2. `SELECT name, age FROM users`
  3. `WHERE` 单条件（数值）
  4. `WHERE` 单条件（字符串）
  5. `WHERE a AND b`
  6. `WHERE a OR b`
  7. `WHERE (a OR b) AND c`
  8. `IS NULL` / `IS NOT NULL`
  9. `ORDER BY` 单列 DESC、多列混合
  10. `GROUP BY` + `COUNT(*)` / `SUM` / 整表 `AVG`
  11. `INNER JOIN` 带别名
  12. `LIMIT`
  13. `LIMIT ... OFFSET`

## 3. 错误行为不变

- 不支持的语法仍抛 `QueryError`（不得改成别的异常或静默返回空）。
- 未知表仍抛 `QueryError`。

## 4. 约束

- **不许修改 `tests/` 下任何文件**，29 个用例必须继续全绿。
- 不许引入第三方依赖。
- `data/` 下的样例数据不许改。
- 重构后不允许出现死代码（旧实现要删干净）。

## 5. 验收方式

- `pytest` 全绿，且 `tests/` 无改动。
- 13 种查询结果与重构前逐条一致。
- `engine/query.py` 不再包含解析/求值实现，各文件 ≤ 200 行。
