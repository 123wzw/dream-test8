"""查询解析与执行。

支持 docs/SQL_SPEC.md 列出的写法：单表/内连接查询、WHERE（比较、
AND/OR、括号、IS [NOT] NULL）、GROUP BY 与聚合、ORDER BY、LIMIT/OFFSET。
纯标准库实现，不依赖任何外部数据库。
"""

import re
from collections import OrderedDict

from engine.data import QueryError, load_table

_TOKEN_RE = re.compile(
    r">=|<=|!=|<>|[(),.*=!<>]"
    r"|'[^']*'|\"[^\"]*\""
    r"|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?"
    r"|\d+(?:\.\d+)?"
)
_AGG_FUNCS = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
_RESERVED = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "IS", "NOT", "NULL", "JOIN",
    "INNER", "ON", "GROUP", "BY", "ORDER", "ASC", "DESC", "LIMIT",
    "OFFSET", "AS",
}


def _tokenize(sql: str) -> list[str]:
    tokens: list[str] = []
    end = 0
    for match in _TOKEN_RE.finditer(sql):
        gap = sql[end:match.start()]
        if gap.strip():
            raise QueryError(f"unrecognized characters: {gap.strip()!r}")
        tokens.append(match.group())
        end = match.end()
    tail = sql[end:]
    if tail.strip():
        raise QueryError(f"unrecognized characters: {tail.strip()!r}")
    return tokens


def _literal(token: str):
    if (token.startswith("'") and token.endswith("'")) or (
        token.startswith('"') and token.endswith('"')
    ):
        return token[1:-1]
    if re.fullmatch(r"\d+", token):
        return int(token)
    return float(token)


def _as_number(value):
    """把 CSV 里的文本单元格按数值解读；无法解读时返回 None。"""
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


class _Rev:
    """排序辅助：反转比较方向，用于 DESC 的单列键。"""

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        if not isinstance(other, _Rev):
            return NotImplemented
        return self.value > other.value

    def __eq__(self, other):
        if not isinstance(other, _Rev):
            return NotImplemented
        return self.value == other.value


class _Parser:
    """递归下降解析器，产出一棵嵌套元组组成的语法树。"""

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    # --- 基础工具 -------------------------------------------------------

    def _peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def _next(self):
        token = self._peek()
        if token is None:
            raise QueryError("unexpected end of query")
        self.pos += 1
        return token

    def _at_kw(self, word: str) -> bool:
        token = self._peek()
        return token is not None and token.upper() == word

    def _match_kw(self, word: str) -> bool:
        if self._at_kw(word):
            self.pos += 1
            return True
        return False

    def _expect(self, word: str):
        if not self._match_kw(word):
            token = self._peek()
            raise QueryError(f"expected {word}, got {token!r}")

    def _parse_nonneg_int(self, clause: str) -> int:
        token = self._next()
        if not re.fullmatch(r"\d+", token):
            raise QueryError(f"{clause} expects a non-negative integer")
        return int(token)

    def _parse_ident(self) -> str:
        token = self._next()
        if token.upper() in _RESERVED or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*", token
        ):
            raise QueryError(f"invalid identifier: {token!r}")
        return token.lower()

    # --- 顶层结构 -------------------------------------------------------

    def parse(self) -> dict:
        if not self.tokens or self.tokens[0].upper() != "SELECT":
            raise QueryError("only SELECT is supported")
        self.pos = 1

        select = self._parse_select_list()
        self._expect("FROM")
        table, alias = self._parse_table_ref()

        joins = []
        while self._at_kw("JOIN") or self._at_kw("INNER"):
            if self._match_kw("INNER"):
                pass
            self._expect("JOIN")
            join_table, join_alias = self._parse_table_ref()
            self._expect("ON")
            on_expr = self._parse_expr()
            joins.append(
                {"table": join_table, "alias": join_alias or join_table, "on": on_expr}
            )

        where = self._parse_expr() if self._match_kw("WHERE") else None

        group_by = []
        if self._match_kw("GROUP"):
            self._expect("BY")
            group_by = self._parse_column_list()

        order_by = []
        if self._match_kw("ORDER"):
            self._expect("BY")
            order_by = self._parse_order_list()

        limit = offset = None
        if self._match_kw("LIMIT"):
            limit = self._parse_nonneg_int("LIMIT")
        if self._match_kw("OFFSET"):
            offset = self._parse_nonneg_int("OFFSET")

        if self.pos != len(self.tokens):
            raise QueryError(f"unexpected token: {self._peek()!r}")

        return {
            "select": select,
            "table": table,
            "alias": alias or table,
            "joins": joins,
            "where": where,
            "group_by": group_by,
            "order_by": order_by,
            "limit": limit,
            "offset": offset,
        }

    def _parse_table_ref(self):
        name = self._parse_ident()
        alias = None
        if self._match_kw("AS"):
            alias = self._parse_ident()
        elif self._peek() is not None and self._peek().upper() not in _RESERVED:
            alias = self._parse_ident()
        return name, alias

    def _parse_select_list(self) -> list[dict]:
        items = []
        while True:
            if self._peek() == "*":
                self._next()
                expr = ("star",)
            else:
                expr = self._parse_operand()
            alias = None
            if self._match_kw("AS"):
                alias = self._parse_ident()
            elif (
                self._peek() not in (None, ",")
                and self._peek().upper() not in _RESERVED
            ):
                alias = self._parse_ident()
            items.append({"expr": expr, "alias": alias})
            if not self._match_comma():
                break
        if not items:
            raise QueryError("empty SELECT list")
        return items

    def _parse_column_list(self) -> list:
        refs = []
        while True:
            ref = self._parse_column_ref()
            refs.append(ref)
            if not self._match_comma():
                break
        return refs

    def _parse_order_list(self) -> list[tuple]:
        order = []
        while True:
            expr = self._parse_operand()
            descending = False
            if self._match_kw("ASC"):
                descending = False
            elif self._match_kw("DESC"):
                descending = True
            order.append((expr, descending))
            if not self._match_comma():
                break
        return order

    def _match_comma(self) -> bool:
        if self._peek() == ",":
            self.pos += 1
            return True
        return False

    # --- 表达式 ---------------------------------------------------------

    def _parse_expr(self):
        return self._parse_or()

    def _parse_or(self):
        node = self._parse_and()
        while self._match_kw("OR"):
            node = ("or", node, self._parse_and())
        return node

    def _parse_and(self):
        node = self._parse_predicate()
        while self._match_kw("AND"):
            node = ("and", node, self._parse_predicate())
        return node

    def _parse_predicate(self):
        left = self._parse_operand()
        if self._match_kw("IS"):
            negated = self._match_kw("NOT")
            self._expect("NULL")
            return ("is_null", left, negated)
        token = self._peek()
        if token in ("=", "!=", "<>", ">", ">=", "<", "<="):
            self._next()
            right = self._parse_operand()
            return ("cmp", "!=" if token == "<>" else token, left, right)
        return left

    def _parse_operand(self):
        token = self._peek()
        if token is None:
            raise QueryError("unexpected end of expression")
        if token == "(":
            self._next()
            node = self._parse_expr()
            if self._next() != ")":
                raise QueryError("missing closing parenthesis")
            return node
        if token.startswith("'") or token.startswith('"'):
            self._next()
            return ("lit", _literal(token))
        if re.fullmatch(r"\d+(?:\.\d+)?", token):
            self._next()
            return ("lit", _literal(token))
        if token.upper() == "NULL":
            self._next()
            return ("lit", None)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token):
            # 函数调用或裸列名
            if self.tokens[self.pos + 1 : self.pos + 2] == ["("]:
                return self._parse_func_call(token)
            self._next()
            return ("col", None, token.lower())
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*", token):
            self._next()
            qualifier, name = token.split(".")
            return ("col", qualifier.lower(), name.lower())
        raise QueryError(f"unexpected token in expression: {token!r}")

    def _parse_func_call(self, name: str):
        func = name.upper()
        if func not in _AGG_FUNCS:
            raise QueryError(f"unknown function: {name}")
        self._next()  # 函数名
        self._next()  # (
        if self._peek() == "*":
            self._next()
            if self._next() != ")":
                raise QueryError("malformed function call")
            if func != "COUNT":
                raise QueryError(f"{func}(*) is not supported")
            return ("agg", func.lower(), "*")
        arg = self._parse_operand()
        if self._next() != ")":
            raise QueryError("malformed function call")
        return ("agg", func.lower(), arg)

    def _parse_column_ref(self):
        token = self._next()
        match = re.fullmatch(
            r"(?:([A-Za-z_][A-Za-z0-9_]*)\.)?([A-Za-z_][A-Za-z0-9_]*)", token
        )
        if not match:
            raise QueryError(f"invalid column reference: {token!r}")
        qualifier, name = match.groups()
        return ("col", qualifier.lower() if qualifier else None, name.lower())


# --- 执行 ----------------------------------------------------------------


def _resolve(ref: tuple, combined: dict):
    _, qualifier, name = ref
    if qualifier is not None:
        table = combined.get(qualifier)
        if table is None:
            raise QueryError(f"unknown table alias: {qualifier}")
        if name not in table:
            raise QueryError(f"unknown column: {qualifier}.{name}")
        return table[name]
    candidates = [alias for alias, row in combined.items() if name in row]
    if not candidates:
        raise QueryError(f"unknown column: {name}")
    if len(candidates) > 1:
        raise QueryError(f"ambiguous column: {name}")
    return combined[candidates[0]][name]


def _eval(node: tuple, combined: dict):
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "col":
        return _resolve(node, combined)
    if kind == "is_null":
        value = _eval(node[1], combined)
        result = value is None
        return not result if node[2] else result
    if kind == "cmp":
        _, op, left_node, right_node = node
        left = _eval(left_node, combined)
        right = _eval(right_node, combined)
        if left is None or right is None:
            return False
        if isinstance(right, (int, float)) or isinstance(left, (int, float)):
            left_num = _as_number(left)
            right_num = _as_number(right)
            if left_num is None or right_num is None:
                return False
            left, right = left_num, right_num
        if op == "=":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right
        if op == ">=":
            return left >= right
        if op == "<":
            return left < right
        if op == "<=":
            return left <= right
        raise QueryError(f"unknown operator: {op}")
    if kind == "and":
        return _eval(node[1], combined) and _eval(node[2], combined)
    if kind == "or":
        return _eval(node[1], combined) or _eval(node[2], combined)
    raise QueryError("expression cannot be evaluated in WHERE")


def _build_combined(ast: dict) -> list[dict]:
    """嵌套循环 INNER JOIN，每行是 {别名: 原始行} 的字典。"""
    base_rows = load_table(ast["table"])
    combined_rows = [{ast["alias"]: row} for row in base_rows]
    for join in ast["joins"]:
        right_rows = load_table(join["table"])
        joined = []
        for left in combined_rows:
            for right in right_rows:
                candidate = dict(left)
                candidate[join["alias"]] = right
                if _eval(join["on"], candidate):
                    joined.append(candidate)
        combined_rows = joined
    return combined_rows


def _output_name(item: dict) -> str:
    if item["alias"] is not None:
        return item["alias"]
    expr = item["expr"]
    if expr[0] == "col":
        return expr[2]
    if expr[0] == "agg":
        arg = expr[2]
        arg_name = "star" if arg == "*" else (arg[2] if arg[0] == "col" else "expr")
        return f"{expr[1]}_{arg_name}"
    raise QueryError("SELECT item requires an alias")


def _project_star(combined: dict, multiple_tables: bool) -> dict:
    if not multiple_tables:
        row = next(iter(combined.values()))
        return dict(row)
    result = {}
    for alias, row in combined.items():
        for column, value in row.items():
            result[f"{alias}_{column}"] = value
    return result


def _aggregate(func: str, arg, members: list[dict]):
    if func == "count" and arg == "*":
        return len(members)
    values = [_eval(arg, row) for row in members]
    values = [value for value in values if value is not None]
    if func == "count":
        return len(values)
    if not values:
        return None
    numbers = [_as_number(value) for value in values]
    if func in ("sum", "avg"):
        if any(number is None for number in numbers):
            raise QueryError(f"{func.upper()} requires numeric values")
        total = float(sum(numbers))
        if func == "avg":
            return total / len(numbers)
        return int(total) if total.is_integer() else total
    # MIN / MAX：数值列按数值比较，否则按原始值比较
    if all(number is not None for number in numbers):
        ordered = sorted(numbers)
        return ordered[-1] if func == "max" else ordered[0]
    ordered = sorted(values)
    return ordered[-1] if func == "max" else ordered[0]


def _sort_value(value):
    number = _as_number(value)
    if number is not None:
        return ("n", number)
    return ("s", str(value))


def _order_key(expr: tuple, combined: dict, descending: bool):
    value = _eval(expr, combined)
    if value is None:
        # 首标记 0 = NULL 排最前（ASC），2 = NULL 排最后（DESC）；
        # 与非 NULL 的标记 1 不同，两类键不会逐元素比较
        return (2 if descending else 0, None)
    comparable = _sort_value(value)
    return (1, _Rev(comparable) if descending else comparable)


def _project_row(select: list[dict], combined: dict, multiple_tables: bool) -> dict:
    output = {}
    for item in select:
        if item["expr"] == ("star",):
            output.update(_project_star(combined, multiple_tables))
        else:
            output[_output_name(item)] = _eval(item["expr"], combined)
    return output


def query(sql: str) -> list[dict]:
    tokens = _tokenize(sql.strip().rstrip(";").strip())
    ast = _Parser(tokens).parse()

    combined_rows = _build_combined(ast)
    if ast["where"] is not None:
        combined_rows = [
            row for row in combined_rows if _eval(ast["where"], row)
        ]

    select = ast["select"]
    has_agg = any(item["expr"][0] == "agg" for item in select)
    multiple_tables = bool(ast["joins"])

    if has_agg or ast["group_by"]:
        results = _execute_grouping(ast, select, combined_rows)
    elif ast["order_by"]:
        # 稳定排序：从最后一个排序列往前，逐个稳定排序
        for expr, descending in reversed(ast["order_by"]):
            combined_rows.sort(
                key=lambda row, expr=expr, desc=descending: _order_key(
                    expr, row, desc
                )
            )
        results = [
            _project_row(select, row, multiple_tables) for row in combined_rows
        ]
    else:
        results = [
            _project_row(select, row, multiple_tables) for row in combined_rows
        ]

    # --- 分页 ----------------------------------------------------------
    offset = ast["offset"] or 0
    if ast["limit"] is not None:
        results = results[offset : offset + ast["limit"]]
    elif offset:
        results = results[offset:]
    return results


def _execute_grouping(ast: dict, select: list[dict], combined_rows: list[dict]):
    group_refs = set(ast["group_by"])
    if ast["group_by"]:
        groups: dict = OrderedDict()
        for row in combined_rows:
            key = tuple(_eval(ref, row) for ref in ast["group_by"])
            groups.setdefault(key, []).append(row)
    else:
        # 无 GROUP BY：整表作为一组；空结果集不产生分组
        groups = OrderedDict()
        if combined_rows:
            groups[()] = list(combined_rows)

    results = []
    for members in groups.values():
        output = {}
        for item in select:
            expr = item["expr"]
            name = _output_name(item)
            if expr[0] == "agg":
                output[name] = _aggregate(expr[1], expr[2], members)
            else:
                if expr[0] != "col" or expr not in group_refs:
                    raise QueryError(
                        "non-aggregated column must appear in GROUP BY"
                    )
                output[name] = _eval(expr, members[0])
        results.append(output)

    # 分组结果上排序：ORDER BY 列按输出列名解析
    if ast["order_by"]:
        for expr, descending in reversed(ast["order_by"]):
            name = expr[2] if expr[0] == "col" else _output_name(
                {"expr": expr, "alias": None}
            )

            def key_func(row, name=name, descending=descending):
                value = row.get(name)
                if value is None:
                    return (2 if descending else 0, None)
                comparable = _sort_value(value)
                return (1, _Rev(comparable) if descending else comparable)

            results.sort(key=key_func)
    return results
