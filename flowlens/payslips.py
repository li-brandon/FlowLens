"""Workday payslip import: net pay as the source of truth for paychecks.

A bank CSV only sees the part of each paycheck that lands in an account it tracks.
When direct deposit is split across accounts (brokerage, crypto, a disconnected
bank), the payslip's net pay is the only complete number. Importing payslips:

1. reads Workday's export (``.xlsx`` or ``.csv``; title rows above the header are fine),
2. turns each payslip into one income row for its net pay, and
3. drops the CSV's own paycheck deposits inside the payslip date range, so pay is
   never counted twice. Other income (interest, Zelle, refunds) is kept.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

import pandas as pd

from .loader import _clean_amount

ACCOUNT = "Workday"
CATEGORY = "Paychecks"
# Deposits can post a day or two before or after the pay date.
MATCH_WINDOW = pd.Timedelta(days=3)

_DATE_WORDS = ("pay date", "check date", "payment date", "date")
_NET_WORDS = ("net pay", "net amount", "net")
_GROSS_WORDS = ("gross pay", "gross amount", "gross")


class PayslipError(ValueError):
    """The file can't be read as a payslip export."""


@dataclass(frozen=True)
class Columns:
    date: str
    net: str
    gross: str | None = None


def read_table(data: bytes, filename: str) -> pd.DataFrame:
    """Read the export and use the first row that looks like a header."""
    try:
        if filename.lower().endswith((".xlsx", ".xlsm")):
            grid = pd.read_excel(io.BytesIO(data), header=None, dtype=str)
        else:
            grid = pd.read_csv(io.BytesIO(data), header=None, dtype=str, keep_default_na=False)
    except Exception as exc:  # bad zip, bad encoding, empty file...
        raise PayslipError(f"The file could not be read: {exc}") from exc
    grid = grid.fillna("")
    for i in range(min(len(grid), 15)):
        cells = [str(c).strip().lower() for c in grid.iloc[i]]
        if any("date" in c for c in cells) and any(("net" in c or "gross" in c) for c in cells):
            table = grid.iloc[i + 1 :].reset_index(drop=True)
            table.columns = _unique([str(c).strip() for c in grid.iloc[i]])
            return table
    raise PayslipError("Couldn't find a header row with a date and a net or gross pay column.")


def _unique(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        n = n or "column"
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n} ({seen[n]})")
    return out


def guess_columns(table: pd.DataFrame) -> Columns:
    def pick(words, exclude=()):
        lowered = {c: c.lower() for c in table.columns}
        for w in words:
            for c, low in lowered.items():
                if w in low and not any(x in low for x in exclude):
                    return c
        return None

    date = pick(_DATE_WORDS, exclude=("period", "start", "end"))
    net = pick(_NET_WORDS, exclude=("ytd", "year"))
    gross = pick(_GROSS_WORDS, exclude=("ytd", "year"))
    if date is None or net is None:
        raise PayslipError("Couldn't find the pay date and net pay columns. Pick them below.")
    return Columns(date=date, net=net, gross=gross)


def parse_payslips(table: pd.DataFrame, cols: Columns) -> pd.DataFrame:
    """One row per payslip: date, net (and gross if known). Totals and blank rows are dropped."""
    out = pd.DataFrame(
        {
            "date": pd.to_datetime(table[cols.date].astype(str).str.strip(), errors="coerce", format="mixed"),
            "net": pd.to_numeric(_clean_amount(table[cols.net]), errors="coerce"),
        }
    )
    if cols.gross:
        out["gross"] = pd.to_numeric(_clean_amount(table[cols.gross]), errors="coerce")
    out = out.dropna(subset=["date", "net"])
    out = out[out["net"] > 0]
    out["date"] = out["date"].dt.normalize()
    return out.sort_values("date").reset_index(drop=True)


def guess_employer(txns: pd.DataFrame) -> str:
    """First word of the most common sizeable income deposit, e.g. "Fidelity"."""
    pay = txns[(txns["type"] == "income") & (txns["amount"].abs() >= 100)]
    words = pay["name"].str.strip().str.split().str[0].dropna()
    return words.value_counts().index[0] if not words.empty else ""


def apply_payslips(txns: pd.DataFrame, payslips: pd.DataFrame, employer: str) -> tuple[pd.DataFrame, int]:
    """Replace the CSV's paycheck deposits with payslip net pay.

    Returns the new transactions and how many CSV rows were replaced. Only income
    rows whose name contains ``employer`` (case-insensitive) and that fall inside
    the payslips' date range are removed.
    """
    if payslips.empty:
        return txns, 0
    first, last = payslips["date"].min() - MATCH_WINDOW, payslips["date"].max() + MATCH_WINDOW
    replaced = pd.Series(False, index=txns.index)
    if employer.strip():
        replaced = (
            txns["type"].eq("income")
            & txns["name"].str.contains(re.escape(employer.strip()), case=False, na=False)
            & txns["date"].between(first, last)
        )
    rows = pd.DataFrame(
        {
            "row": 0,
            "date": payslips["date"],
            "name": "Paycheck (Workday net pay)",
            "amount": -payslips["net"],
            "type": "income",
            "category": CATEGORY,
            "group": "",
            "account": ACCOUNT,
            "excluded": False,
        }
    )
    out = pd.concat([txns[~replaced], rows], ignore_index=True)
    return out.sort_values("date", kind="stable").reset_index(drop=True), int(replaced.sum())
