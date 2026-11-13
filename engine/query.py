"""查询解析与执行。"""

import re

from engine.data import QueryError, load_table

_TOKEN_RE = re.compile(r"[(),.*=!<>]+|'[^']*'|\"[^\"]*\"|[^\s(),.*=!<>]+")
_OPS = {"=", "!=", ">", ">=", "<", "<="}


def _tokenize(sql: str) -> list[str]:
    return _TOKEN_RE.findall(sql)


def _to_number(token: str):
    try:
        return int(token)
    except ValueError:
        try:
            return float(token)
        except ValueError:
            return None


def _literal(token: str):
    if token.startswith("'") and token.endswith("'"):
        return token[1:-1]
    number = _to_number(token)
    return number if number is not None else token


def _compare(left, op: str, right) -> bool:
    if left is None:
        return False
    if isinstance(right, (int, float)):
        try:
            left = float(left)
        except (TypeError, ValueError):
            return False
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


def _split_clauses(tokens: list[str]) -> dict:
    clauses: dict[str, list[str]] = {"select": [], "from": [], "where": []}
    current = "select"
    for token in tokens:
        upper = token.upper()
        if upper in ("SELECT",):
            current = "select"
            continue
        if upper == "FROM":
            current = "from"
            continue
        if upper == "WHERE":
            current = "where"
            continue
        if current == "select" and token == ",":
            continue
        clauses[current].append(token)
    return clauses


def _eval_where(tokens: list[str], row: dict) -> bool:
    if not tokens:
        return True
    if len(tokens) == 3:
        column, op, raw = tokens
        return _compare(row.get(column.lower()), op, _literal(raw))
    raise QueryError("unsupported WHERE expression")


def _project(columns: list[str], row: dict) -> dict:
    if columns == ["*"]:
        return dict(row)
    return {col.lower(): row.get(col.lower()) for col in columns}


def query(sql: str) -> list[dict]:
    tokens = _tokenize(sql.strip().rstrip(";"))
    if not tokens or tokens[0].upper() != "SELECT":
        raise QueryError("only SELECT is supported")

    clauses = _split_clauses(tokens)
    columns = clauses["select"]
    if not clauses["from"]:
        raise QueryError("missing FROM")
    table_name = clauses["from"][0]

    rows = load_table(table_name)
    result = [_project(columns, row) for row in rows if _eval_where(clauses["where"], row)]
    return result
