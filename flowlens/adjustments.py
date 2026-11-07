"""Manual income adjustments: money that never shows up in the CSV.

Examples: paychecks split into accounts Copilot doesn't track as transactions
(brokerage, crypto), or an account that was disconnected. Each adjustment turns
into ordinary ``income`` rows, so metrics, the Sankey and projections all count it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

ONCE, BIWEEKLY, MONTHLY = "Once", "Every 2 weeks", "Monthly"
REPEATS: tuple[str, ...] = (ONCE, BIWEEKLY, MONTHLY)
ACCOUNT = "Manual adjustment"

_STEP = {BIWEEKLY: pd.DateOffset(weeks=2), MONTHLY: pd.DateOffset(months=1)}


@dataclass(frozen=True)
class Adjustment:
    name: str
    amount: float  # positive = money in
    repeats: str
    start: date
    end: date | None = None  # recurring only; None = up to the latest transaction

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "amount": self.amount,
            "repeats": self.repeats,
            "start": self.start.isoformat(),
            "end": self.end.isoformat() if self.end else None,
        }

    @classmethod
    def from_dict(cls, raw) -> Adjustment | None:
        """Build from saved JSON or an editor row; None if the row is incomplete or invalid."""
        try:
            name = str(raw.get("name") or "").strip()
            amount = float(raw.get("amount"))
            repeats = raw.get("repeats") or ONCE
            start = _to_date(raw.get("start"))
            end = _to_date(raw.get("end")) if raw.get("end") not in (None, "") else None
        except (TypeError, ValueError):
            return None
        if not name or not amount > 0 or repeats not in REPEATS or start is None:
            return None
        if end is not None and (pd.isna(end) or end < start):
            end = None
        return cls(name=name, amount=amount, repeats=repeats, start=start, end=end)


def _to_date(value) -> date | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return pd.Timestamp(value).date()


def occurrences(adj: Adjustment, until) -> list[pd.Timestamp]:
    start = pd.Timestamp(adj.start)
    if adj.repeats == ONCE:
        return [start]
    last = pd.Timestamp(adj.end) if adj.end else pd.Timestamp(until).normalize()
    # Step from the start each time (start + k steps) so a monthly payday on the
    # 31st comes back to the 31st after February instead of drifting to the 28th.
    dates, k = [], 0
    while (d := start + _STEP[adj.repeats] * k) <= last:
        dates.append(d)
        k += 1
    return dates


def adjustment_rows(adjustments: list[Adjustment], until) -> pd.DataFrame:
    """Income rows in the same shape the loader produces (amount negative = money in)."""
    rows = [
        {
            "row": 0,
            "date": d,
            "name": adj.name,
            "amount": -adj.amount,
            "type": "income",
            "category": adj.name,
            "group": "",
            "account": ACCOUNT,
            "excluded": False,
        }
        for adj in adjustments
        for d in occurrences(adj, until)
    ]
    return pd.DataFrame(rows, columns=["row", "date", "name", "amount", "type", "category", "group", "account", "excluded"])


def with_adjustments(txns: pd.DataFrame, adjustments: list[Adjustment]) -> pd.DataFrame:
    """The transactions plus adjustment rows up to the latest transaction date."""
    if not adjustments or txns.empty:
        return txns
    extra = adjustment_rows(adjustments, txns["date"].max())
    if extra.empty:
        return txns
    out = pd.concat([txns, extra.astype({"excluded": bool})], ignore_index=True)
    return out.sort_values("date", kind="stable").reset_index(drop=True)
