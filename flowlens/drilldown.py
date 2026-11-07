"""Per-category drill-down: metrics, top merchants and transactions."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .calc import expense_rows


@dataclass(frozen=True)
class CategoryDetail:
    total: float
    count: int
    average: float
    top_merchants: pd.Series  # merchant -> net spend, largest first (max 10)
    transactions: pd.DataFrame  # newest first


def category_detail(df: pd.DataFrame, category: str, top_n: int = 10) -> CategoryDetail:
    rows = expense_rows(df)
    rows = rows[rows["category"] == category]
    total = float(rows["amount"].sum())
    count = len(rows)
    merchants = rows.groupby("name")["amount"].sum().astype(float)
    merchants = merchants[merchants > 0].sort_values(ascending=False).head(top_n)
    txns = rows.sort_values(["date", "row"], ascending=[False, True])
    return CategoryDetail(
        total=total,
        count=count,
        average=total / count if count else 0.0,
        top_merchants=merchants,
        transactions=txns,
    )
