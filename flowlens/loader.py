"""CSV import and normalization for Copilot Money exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import IO

import pandas as pd

REQUIRED_COLUMNS: tuple[str, ...] = (
    "date",
    "name",
    "amount",
    "type",
    "category",
    "account",
    "excluded",
)

# Blank categories are grouped here so no spending is hidden.
OTHER_CATEGORY = "Other"

_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0", ""}


class CsvFormatError(ValueError):
    """The file can't be read as a transaction CSV (e.g. required columns are missing)."""


@dataclass
class LoadResult:
    """Clean transactions plus any rows that could not be parsed."""

    transactions: pd.DataFrame
    bad_rows: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=["row", "reason"]))


def load_transactions(source: str | IO) -> LoadResult:
    """Read a Copilot Money CSV and return typed, normalized transactions.

    ``source`` is a path or a file-like object (e.g. a Streamlit upload). Data is only
    read into memory; nothing is written or sent anywhere.

    Raises ``CsvFormatError`` if the file is empty, unreadable or missing required columns.
    """
    try:
        raw = pd.read_csv(source, dtype=str, keep_default_na=False, skipinitialspace=True)
    except pd.errors.EmptyDataError as exc:
        raise CsvFormatError("The file is empty.") from exc
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise CsvFormatError(f"The file could not be read as CSV: {exc}") from exc

    raw.columns = [str(c).strip().lower() for c in raw.columns]
    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise CsvFormatError("Missing required column(s): " + ", ".join(missing))

    df = raw.copy()
    # Line number in the original file (header is line 1).
    df.insert(0, "row", range(2, len(df) + 2))

    for col in ("name", "type", "category", "account", "excluded"):
        df[col] = df[col].astype(str).str.strip()

    dates = pd.to_datetime(df["date"].str.strip(), errors="coerce", format="mixed")
    amounts = pd.to_numeric(_clean_amount(df["amount"]), errors="coerce")
    excluded_text = df["excluded"].str.lower()
    excluded_ok = excluded_text.isin(_TRUE | _FALSE)

    reasons = pd.Series("", index=df.index, dtype=object)
    reasons = _add_reason(reasons, dates.isna(), "unreadable date")
    reasons = _add_reason(reasons, amounts.isna(), "unreadable amount")
    reasons = _add_reason(reasons, ~excluded_ok, "unreadable excluded flag")
    bad_mask = reasons != ""

    bad_rows = pd.DataFrame(
        {"row": df.loc[bad_mask, "row"], "reason": reasons[bad_mask]}
    ).reset_index(drop=True)

    good = df.loc[~bad_mask].copy()
    good["date"] = dates[~bad_mask].dt.normalize()
    good["amount"] = amounts[~bad_mask].astype(float)
    good["type"] = good["type"].str.lower()
    good["category"] = good["category"].where(good["category"] != "", OTHER_CATEGORY)
    good["excluded"] = excluded_text[~bad_mask].isin(_TRUE)
    good = good.reset_index(drop=True)

    return LoadResult(transactions=good, bad_rows=bad_rows)


def _clean_amount(values: pd.Series) -> pd.Series:
    """Strip currency symbols/commas and turn ``(12.34)`` into ``-12.34``."""
    s = values.astype(str).str.strip().str.replace(r"[$,\s]", "", regex=True)
    return s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)


def _add_reason(reasons: pd.Series, mask: pd.Series, text: str) -> pd.Series:
    out = reasons.copy()
    out[mask] = out[mask].where(out[mask] == "", out[mask] + "; ") + text
    return out
