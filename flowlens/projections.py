"""Year-end projections: annualized spend per category against income targets.

A projection takes the net spend in the selected date range, turns it into an
average monthly rate and multiplies by 12. Income is annualized the same way
unless the user enters an override.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .calc import category_totals, total_income

DAYS_PER_MONTH = 365.25 / 12

ON_PACE = "On pace"
OVER = "Over"


def months_in_range(start, end) -> float:
    """Length of the inclusive date range in average-length months."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    days = abs((end - start).days) + 1
    return days / DAYS_PER_MONTH


def annualize(amount: float, months: float) -> float:
    return amount / months * 12 if months > 0 else 0.0


@dataclass(frozen=True)
class Projection:
    months: float
    detected_income: float  # annualized from the range
    annual_income: float  # override if given, else detected
    table: pd.DataFrame  # one row per category, largest projected spend first


def project(
    df: pd.DataFrame,
    start,
    end,
    targets: dict[str, float] | None = None,
    income_override: float | None = None,
) -> Projection:
    """Project annual spend per category and compare it to targets (% of income).

    ``df`` should already be filtered to [start, end]. Categories whose refunds
    exceed spending (net <= 0) project to 0. ``status`` is empty when a category
    has no target.
    """
    targets = targets or {}
    months = months_in_range(start, end)
    detected = annualize(total_income(df), months)
    income = income_override if income_override and income_override > 0 else detected

    cats = category_totals(df).clip(lower=0)
    rows = []
    for name, spent in cats.items():
        projected = annualize(float(spent), months)
        target_pct = targets.get(name)
        target_amount = income * target_pct / 100 if target_pct is not None else None
        if target_amount is None:
            status = ""
        else:
            status = OVER if projected > target_amount else ON_PACE
        rows.append(
            {
                "category": name,
                "spent": float(spent),
                "monthly": float(spent) / months,
                "projected": projected,
                "pct_of_income": projected / income * 100 if income > 0 else None,
                "target_pct": target_pct,
                "target_amount": target_amount,
                "status": status,
            }
        )
    table = pd.DataFrame(
        rows,
        columns=[
            "category", "spent", "monthly", "projected",
            "pct_of_income", "target_pct", "target_amount", "status",
        ],
    )
    table = table.sort_values("projected", ascending=False, kind="stable").reset_index(drop=True)
    return Projection(months=months, detected_income=detected, annual_income=income, table=table)
