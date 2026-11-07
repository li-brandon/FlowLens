"""Date range presets and filtering."""

from __future__ import annotations

import pandas as pd

ALL_TIME = "All Time"
CUSTOM = "Custom"

# Preset name -> how far back from the end date the range reaches.
_OFFSETS: dict[str, pd.DateOffset] = {
    "Last Week": pd.DateOffset(days=7),
    "Last Month": pd.DateOffset(months=1),
    "60 Days": pd.DateOffset(days=60),
    "90 Days": pd.DateOffset(days=90),
    "6 Months": pd.DateOffset(months=6),
    "Year": pd.DateOffset(years=1),
}

PRESETS: tuple[str, ...] = (*_OFFSETS, ALL_TIME)


def preset_range(preset: str, dates: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the inclusive (start, end) for ``preset``.

    The range ends on the latest transaction date, so an older export still shows data
    for "Last Month" etc. ``All Time`` spans every transaction.
    """
    if dates.empty:
        today = pd.Timestamp.today().normalize()
        return today, today
    first, last = dates.min().normalize(), dates.max().normalize()
    if preset == ALL_TIME:
        return first, last
    if preset not in _OFFSETS:
        raise ValueError(f"Unknown preset: {preset}")
    start = last - _OFFSETS[preset] + pd.Timedelta(days=1)
    return max(start, first), last


def filter_range(df: pd.DataFrame, start, end) -> pd.DataFrame:
    """Rows whose date falls within [start, end], both inclusive."""
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if start > end:
        start, end = end, start
    return df[(df["date"] >= start) & (df["date"] <= end)]
