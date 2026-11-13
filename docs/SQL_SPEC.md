# 查询语法要求（SQL_SPEC）

本文是验收依据。列出的写法都必须支持，结果集要正确。

## 1. 基础查询

```sql
SELECT * FROM users
SELECT name, age FROM users
SELECT name FROM users WHERE age > 30
```

- 列名大小写不敏感。
- `*` 返回全部列，列顺序与 CSV 表头一致。

## 2. WHERE 条件

- 比较运算：`=`、`!=`、`>`、`>=`、`<`、`<=`
- 逻辑组合：`AND`、`OR`，且支持括号决定优先级
- NULL 判断：`IS NULL`、`IS NOT NULL`

## 3. 排序

```sql
SELECT name, age FROM users ORDER BY age DESC
SELECT name FROM users ORDER BY city ASC, age DESC
```

- 支持多列排序，每列可指定 `ASC`（默认）或 `DESC`。

## 4. 聚合与分组

```sql
SELECT city, COUNT(*) AS cnt FROM users GROUP BY city
SELECT status, SUM(amount) AS total FROM orders GROUP BY status
SELECT AVG(age) AS avg_age FROM users
```

- 支持 `COUNT(*)`、`COUNT(col)`、`SUM`、`AVG`、`MIN`、`MAX`。
- 聚合函数忽略 NULL 值；`COUNT(*)` 不忽略。
- 出现聚合函数但无 `GROUP BY` 时，整表作为一组。

## 5. JOIN

```sql
SELECT u.name, o.amount FROM users u JOIN orders o ON u.id = o.user_id
```

- 支持 `INNER JOIN`（`JOIN` 即内连接），带表别名。
- 结果列可用 `表别名.列名` 或 `列名` 指定。

## 6. 分页

```sql
SELECT * FROM users LIMIT 10
SELECT * FROM users LIMIT 10 OFFSET 20
```

## 7. 其他约定

- 字符串字面量用单引号，如 `city = 'Beijing'`。
- 数值字面量不加引号。
- 查询不修改数据。
- 不支持的语法必须抛 `QueryError`，不得静默返回错误结果。

## 8. 验收方式

- 对 `data/` 下的数据执行上述每种写法，结果行数、列名、顺序、取值都要正确。
- NULL 参与比较时不得被当成 0 或空串。
