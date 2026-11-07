"""Year-end projections and per-category targets.

The selected date range is treated as a sample of a typical period:

- Months in range = inclusive days / (365.25 / 12), so a 30-day window is ~0.99 months.
- Average monthly spend per category = net spend in range / months in range.
- Projected annual spend = average monthly spend * 12.
- Annual income (auto-detected) = income in range annualized the same way. A manual
  override, when given, replaces it.
- A target is a percent of annual income. A category is **On pace** when its projected
  annual spend is at or below the target amount, and **Over** otherwise. Categories with
  no target show **No target**; targets can't be judged when annual income is zero
  (**No income**).
"""

from __future__ import annotations

import pandas as pd

from .calc import category_totals, total_income

DAYS_PER_MONTH = 365.25 / 12

ON_PACE = "On pace"
OVER = "Over"
NO_TARGET = "No target"
NO_INCOME = "No income"

COLUMNS = [
    "category",
    "spent",
    "monthly_avg",
    "projected_annual",
    "target_pct",
    "target_amount",
    "status",
]


def months_in_range(start, end) -> float:
    """Length of the inclusive range [start, end] in average-length months."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start > end:
        start, end = end, start
    days = (end - start).days + 1
    return days / DAYS_PER_MONTH


def annualize(amount: float, months: float) -> float:
    """Scale an amount observed over ``months`` to a 12-month figure."""
    if months <= 0:
        return 0.0
    return amount / months * 12


def detected_annual_income(df: pd.DataFrame, start, end) -> float:
    """Income in the range, annualized."""
    return annualize(total_income(df), months_in_range(start, end))


def target_status(projected: float, target_pct: float | None, annual_income: float) -> str:
    if target_pct is None:
        return NO_TARGET
    if annual_income <= 0:
        return NO_INCOME
    return ON_PACE if projected <= target_pct / 100 * annual_income else OVER


def project_categories(
    df: pd.DataFrame,
    start,
    end,
    annual_income: float,
    targets: dict[str, float] | None = None,
) -> pd.DataFrame:
    """One row per spending category in ``df`` (already filtered to [start, end]).

    Columns: ``category``, ``spent`` (net spend in range), ``monthly_avg``,
    ``projected_annual``, ``target_pct`` (NaN when unset), ``target_amount`` (NaN when
    unset), ``status``. Sorted by projected annual spend, largest first.
    """
    targets = targets or {}
    totals = category_totals(df)
    if totals.empty:
        return pd.DataFrame(columns=COLUMNS)

    months = months_in_range(start, end)
    rows = []
    for category, spent in totals.items():
        projected = annualize(spent, months)
        pct = targets.get(category)
        rows.append(
            {
                "category": category,
                "spent": spent,
                "monthly_avg": spent / months if months > 0 else 0.0,
                "projected_annual": projected,
                "target_pct": float("nan") if pct is None else float(pct),
                "target_amount": float("nan") if pct is None else pct / 100 * annual_income,
                "status": target_status(projected, pct, annual_income),
            }
        )
    out = pd.DataFrame(rows, columns=COLUMNS)
    return out.sort_values("projected_annual", ascending=False, ignore_index=True)
