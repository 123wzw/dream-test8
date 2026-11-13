# mini-sql 补齐报告

对照 `docs/SQL_SPEC.md` 逐条核查后，原 `engine/query.py`（103 行）只能做
"单表 + 单个比较条件"的查询。本次重写为 tokenizer + 递归下降解析器 + 执行器，
规范列出的写法已全部支持。纯标准库实现（`re`、`collections`，数据层仍用
`csv`），未调用 sqlite3 或任何外部数据库；`data/` 目录与运行配置未改动。

- 新增测试：`tests/test_spec.py`，22 个用例，在修复前 19 个失败、3 个因旧实现
  碰巧满足而通过（保留为回归用例）。
- 修复后：`pytest -q` 共 **29 passed**（22 个 spec 用例 + 7 个原有功能用例），
  `tests/test_functional.py` 的断言一字未改。

---

## 1. WHERE 的 AND / OR / 括号（对应 SQL_SPEC 第 2 条）

- **代码位置**
  - 旧：`engine/query.py:75-81`（`_eval_where` 只接受恰好 3 个 token 的单一比较）、
    `engine/query.py:55-72`（`_split_clauses` 不认识 AND/OR/括号，全部塞进 where 列表）
  - 新：`engine/query.py:252`（`_parse_or`）、`engine/query.py:258`（`_parse_and`）、
    `engine/query.py:277`（`_parse_operand` 处理括号子表达式）、
    `engine/query.py:357`（`_eval` 递归求值 and/or 节点）
- **当前（修复前）行为**：`WHERE city = 'Beijing' AND age > 35` 抛
  `QueryError: unsupported WHERE expression`；多条件查询一条都跑不了。
- **正确行为**：AND 优先级高于 OR，括号可改变优先级，按布尔组合逐行过滤。
- **修复方式**：删掉扁平的 `_split_clauses`/`_eval_where`，改为递归下降解析，
  表达式文法为 `or := and (OR and)*`、`and := predicate (AND predicate)*`、
  `predicate` 支持括号嵌套；执行期对语法树递归求值（短路语义）。
- **测试用例**：`test_where_and`、`test_where_or`、
  `test_where_parentheses_change_precedence`、
  `test_where_or_without_parentheses_uses_or_precedence`

## 2. IS NULL / IS NOT NULL（对应 SQL_SPEC 第 2 条）

- **代码位置**
  - 旧：`engine/query.py:75-81`，语法树里根本没有 NULL 判断分支，`IS` 被当成普通 token
  - 新：`engine/query.py:264`（`_parse_predicate` 识别 `IS [NOT] NULL`）、
    `engine/query.py:363`（`_eval` 的 `is_null` 分支）
- **当前（修复前）行为**：`WHERE manager_id IS NULL` 报
  `QueryError: unknown operator: IS`（token 数不为 3 时则报 unsupported WHERE）。
- **正确行为**：`IS NULL` 仅当单元格为 Python `None`（CSV 空字段）时为真；
  `IS NOT NULL` 取反；空串不与 NULL 混淆。
- **修复方式**：谓词解析中增加 `("is_null", 列节点, 是否取反)` 节点，执行期只判
  `value is None`。
- **测试用例**：`test_where_is_null`、`test_where_is_not_null`

## 3. NULL 参与比较不得当成 0 或空串（对应 SQL_SPEC 第 2、8 条）

- **代码位置**
  - 旧：`engine/query.py:32-39`（`_compare` 只挡了左值为 NULL，右值为 NULL 时
    会落到 Python 比较，语义不完整）
  - 新：`engine/query.py:357` 起的 `cmp` 分支，比较前同时检查左右值
- **当前（修复前）行为**：Dave 的 age 为空，左值 NULL 时旧代码恰好返回 False，
  简单用例能过；但任何一侧为 NULL 的其他写法（如 `0 = age`、JOIN 键含空值）
  没有统一保证。
- **正确行为**：任一侧为 NULL，六个比较运算一律返回 False（UNKNOWN 按不命中处理），
  绝不把 NULL 转成 0 或 `""` 再比较。
- **修复方式**：比较节点求值时先判断 `left is None or right is None → False`，
  再做数值/字符串比较；数值与文本混用且无法转数值时也返回 False 而非抛异常。
- **测试用例**：`test_null_compare_not_treated_as_zero`（旧代码碰巧通过，
  现作为回归保障保留）

## 4. ORDER BY 单列/多列、ASC/DESC（对应 SQL_SPEC 第 3 条）

- **代码位置**
  - 旧：`engine/query.py:55-72`，`_split_clauses` 的子句字典只有
    select/from/where，ORDER BY 的 token 全部落进 where
  - 新：`engine/query.py:159-162`（解析 ORDER BY 子句）、
    `engine/query.py:227`（`_parse_order_list`）、
    `engine/query.py:472`（`_order_key`）、`engine/query.py:508-515`
    （多列稳定排序：从最后一个排序列向前依次稳定排序）
- **当前（修复前）行为**：`ORDER BY age DESC` 被拼成 7 个 where token，
  报 `unsupported WHERE expression`；`test_order_by_*` 实际表现为结果保持
  CSV 原顺序，断言失败。
- **正确行为**：支持多列排序，每列独立 ASC（默认）/DESC；数值列按数值大小
  （`"41" > "9"` 不会按字典序排错）；NULL 在 ASC 时排最前、DESC 时排最后；
  同值保持原相对顺序（稳定排序）。
- **修复方式**：解析出 `(表达式, 是否DESC)` 列表；排序键把 NULL 与非 NULL 用
  不同首标记隔开避免跨类型比较，DESC 用反转包装类 `_Rev`（`engine/query.py:63`）
  实现反向比较；利用 Python sort 的稳定性逐列排序。
- **测试用例**：`test_order_by_single_column_desc`、
  `test_order_by_multi_columns`

## 5. 聚合函数与 GROUP BY（对应 SQL_SPEC 第 4 条）

- **代码位置**
  - 旧：无任何聚合概念；`COUNT(*)` 这类带括号的 token 直接让 select/where 解析失配
  - 新：`engine/query.py:308`（`_parse_func_call`，支持
    COUNT/SUM/AVG/MIN/MAX 与 `COUNT(*)`）、`engine/query.py:440`
    （`_aggregate`，NULL 过滤与数值计算）、`engine/query.py:533`
    （`_execute_grouping`：分组、无 GROUP BY 整表一组、聚合排序）
- **当前（修复前）行为**：`SELECT city, COUNT(*) ... GROUP BY city` 抛
  QueryError；无 GROUP BY 的 `AVG(age)` 同样无法解析。
- **正确行为**：
  - 五个聚合函数全部支持；除 `COUNT(*)` 外都忽略 NULL，`COUNT(*)` 统计组内全部行；
  - 有 GROUP BY 时按分组列取值分组，分组按首次出现顺序输出；
  - 无 GROUP BY 但出现聚合函数时整表作为一组（空结果集不产生行，与 SQL 惯例一致）；
  - SELECT 里既不是聚合、也不在 GROUP BY 中的列直接抛 `QueryError`，不静默返回乱值。
- **修复方式**：语法树引入 `("agg", 函数名, 参数)` 节点；执行期用
  `OrderedDict` 按分组键归集，再对每组成员调 `_aggregate`；SUM/AVG 校验数值性，
  MIN/MAX 数值列按数值、文本列按文本比较。
- **测试用例**：`test_group_by_count`、`test_group_by_sum`、
  `test_aggregate_without_group_by_is_whole_table`、
  `test_count_star_vs_count_column`、`test_min_max_ignore_null`、
  `test_group_by_multiple_rows_order_preserved`

## 6. INNER JOIN 与表别名、限定列名（对应 SQL_SPEC 第 5 条）

- **代码位置**
  - 旧：`engine/query.py:97-101`，FROM 后只取第一个 token 当表名，别名、JOIN、
    ON 全部被后续子句逻辑吞掉
  - 新：`engine/query.py:141-151`（解析 JOIN/INNER JOIN + ON 条件）、
    `engine/query.py:186`（`_parse_table_ref`，支持 `表 AS 别名` 和 `表 别名`）、
    `engine/query.py:399`（`_build_combined`，嵌套循环内连接）、
    `engine/query.py:340`（`_resolve`，解析 `别名.列` / 裸列名并检测歧义）
- **当前（修复前）行为**：`users u JOIN orders o ON ...` 中表名被取成
  `users`，其余 token 污染 WHERE，报 unsupported WHERE；关联查询完全不可用。
- **正确行为**：JOIN 即 INNER JOIN，按 ON 条件做嵌套循环匹配，不满足条件的
  组合丢弃；SELECT/WHERE/ON 中可用 `u.name` 限定列，也可用裸列名；裸列名在
  多表中重名（如 `id`）时抛 `QueryError: ambiguous column`，不随便选一张表。
- **修复方式**：每个中间行表示为 `{表别名: 该表原始行字典}`，JOIN 时做笛卡尔
  展开并对 ON 表达式递归求值过滤；列解析先按别名定位表，裸列名全局唯一才放行。
- **测试用例**：`test_inner_join_with_aliases`、
  `test_join_qualified_column_names`

## 7. LIMIT / OFFSET 分页（对应 SQL_SPEC 第 6 条）

- **代码位置**
  - 旧：`engine/query.py:55-72` 不识别 LIMIT/OFFSET 关键字，token 被并入 where
  - 新：`engine/query.py:165-169`（解析，`_parse_nonneg_int` 在
    `engine/query.py:116` 强制非负整数）、`engine/query.py:524-529`（切片分页）
- **当前（修复前）行为**：`LIMIT 2` 被静默忽略，`SELECT id ... LIMIT 2`
  返回全部 6 行（属于规范第 7 条禁止的"静默返回错误结果"）。
- **正确行为**：`LIMIT n`、`LIMIT n OFFSET m` 正确切片；超出表长时返回剩余全部
  行而不报错；另外兼容单独 `OFFSET m`；负数或非整数立即抛 `QueryError`。
- **修复方式**：解析器在末尾消费 LIMIT/OFFSET 并做整数校验，执行期统一在
  排序/分组之后切片，保证分页作用在最终结果集上。
- **测试用例**：`test_limit`、`test_limit_offset`、`test_limit_beyond_table_size`

## 8. 字面量、大小写不敏感与非法语法必须抛 QueryError（对应 SQL_SPEC 第 1、7 条）

- **代码位置**
  - 旧：`engine/query.py:11-12`（tokenizer 对无法识别的字符无感知）、
    `engine/query.py:90-103`（`query` 不检查多余 token，未知子句被静默吞掉）
  - 新：`engine/query.py:27-39`（`_tokenize` 对字符间隙做校验，非法字符报错）、
    `engine/query.py:122-130`（标识符不得是保留字）、
    `engine/query.py:170-172`（解析到结尾仍有 token 即报 unexpected token）、
    `engine/query.py:42-50`（`_literal`：单引号字符串、整数/浮点数字面量）
- **当前（修复前）行为**：关键字大小写与列名小写化部分可用，但
  `... GROUP BY city TYPO`、`WHERE`（缺表达式）、`LIMIT -1` 等要么静默返回
  错误结果，要么抛出含义不清的错误；`UPDATE ...` 之外的非法语句没有统一拦截。
- **正确行为**：列名、表别名、关键字全部大小写不敏感，输出列名统一小写；
  单引号字符串与裸数值按规范区分；任何不支持的语法、未知列/表、歧义列、
  非法函数、残缺表达式都抛 `QueryError`，绝不静默返回。
- **修复方式**：tokenizer 报告未识别字符；解析器每个环节用 `_expect`/保留字
  校验/结尾校验兜底；列解析集中在 `_resolve` 统一抛 unknown/ambiguous 错误；
  非 SELECT 语句在 `parse()` 入口直接拒绝。
- **测试用例**：`test_column_and_keyword_case_insensitive`、
  `test_unsupported_syntax_raises_query_error`

---

## 约束遵守情况

| 约束 | 情况 |
|---|---|
| 不改 `docs/SQL_SPEC.md` | 未改动 |
| 不改 `tests/test_functional.py` 断言 | 未改动，7 个用例全部通过 |
| 不外包给 sqlite3/其他数据库 | 全仓 grep 无 sqlite；解析与执行均为本项目代码 |
| 只用标准库 | 仅用 `re`、`collections.OrderedDict`（数据层原有的 `csv`/`os`/`pathlib` 未动） |
| 不动数据目录/运行配置 | `data/`、`engine/data.py`、`pytest.ini` 均未改动 |
| 测试 | `.venv/Scripts/python -m pytest -q` → 29 passed |
