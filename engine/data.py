"""CSV 数据加载。"""

import csv
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class QueryError(Exception):
    pass


def data_dir() -> Path:
    return Path(os.environ.get("MINISQL_DATA", str(BASE_DIR / "data")))


def load_table(name: str) -> list[dict]:
    path = data_dir() / f"{name}.csv"
    if not path.exists():
        raise QueryError(f"unknown table: {name}")
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = []
        for raw in reader:
            row = {}
            for key, value in raw.items():
                text = (value or "").strip()
                row[key.lower()] = None if text == "" else text
            rows.append(row)
        return rows
