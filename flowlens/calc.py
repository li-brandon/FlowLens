"""Income, expense and savings calculations.

Rules (amounts follow the Copilot Money sign convention: positive = money out):

- Income: rows with type ``income``, counted as absolute values. The ``excluded``
  flag does not remove income.
- Expenses: every other row except transfers and rows marked ``excluded``.
  Refunds (negative amounts) reduce their category's total.
- Transfers: any type containing ``transfer`` (e.g. ``internal transfer``) is ignored.
- Savings = income - expenses; savings rate = savings / income * 100, or ``None``
  when there is no income.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Summary:
    income: float
    expenses: float
    savings: float
    savings_rate: float | None  # percent; None when income is zero


def is_income(df: pd.DataFrame) -> pd.Series:
    return df["type"].eq("income")


def is_transfer(df: pd.DataFrame) -> pd.Series:
    return df["type"].str.contains("transfer", regex=False)


def income_rows(df: pd.DataFrame) -> pd.DataFrame:
    return df[is_income(df)]


def expense_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that count as spending (refunds included as negatives)."""
    mask = ~is_income(df) & ~is_transfer(df) & ~df["excluded"].astype(bool)
    return df[mask]


def total_income(df: pd.DataFrame) -> float:
    return float(income_rows(df)["amount"].abs().sum())


def category_totals(df: pd.DataFrame) -> pd.Series:
    """Net spend per category (refunds subtracted), largest first."""
    exp = expense_rows(df)
    if exp.empty:
        return pd.Series(dtype=float, name="amount")
    totals = exp.groupby("category")["amount"].sum().astype(float)
    return totals.sort_values(ascending=False)


def summarize(df: pd.DataFrame) -> Summary:
    income = total_income(df)
    expenses = float(category_totals(df).sum())
    savings = income - expenses
    rate = (savings / income * 100) if income > 0 else None
    return Summary(income=income, expenses=expenses, savings=savings, savings_rate=rate)
