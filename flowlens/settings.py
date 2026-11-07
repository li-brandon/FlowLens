"""Saved user settings: category targets, the annual income override and income adjustments.

Stored as JSON in ``~/.flowlens/settings.json``, outside the repo, so it survives
app restarts and can never be committed. Only category names, the labels you give
adjustments, dates and numbers are stored, never transactions from the CSV.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

from .adjustments import Adjustment

DEFAULT_PATH = Path.home() / ".flowlens" / "settings.json"


@dataclass
class Settings:
    targets: dict[str, float] = field(default_factory=dict)  # category -> % of income
    income_override: float | None = None  # annual; None = auto-detect
    adjustments: list[Adjustment] = field(default_factory=list)  # income missing from the CSV
    warning: str | None = None  # set when a broken file was moved aside


def _number(x) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if math.isfinite(x) and x >= 0 else None


def load_settings(path: Path = DEFAULT_PATH) -> Settings:
    """Read settings. A missing file gives defaults.

    A file that can't be read is renamed to ``settings.json.bad`` (so nothing is
    lost) and defaults are returned with a warning.
    """
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not isinstance(raw.get("targets", {}), dict):
            raise ValueError("unexpected structure")
    except (OSError, ValueError) as exc:
        bad = path.with_name(path.name + ".bad")
        path.replace(bad)
        return Settings(warning=f"Saved settings couldn't be read ({exc}); moved to {bad}.")

    targets = {}
    for name, pct in raw.get("targets", {}).items():
        value = _number(pct)
        if isinstance(name, str) and value is not None:
            targets[name] = value
    raw_adjustments = raw.get("adjustments", [])
    adjustments = [
        a for a in (Adjustment.from_dict(r) for r in raw_adjustments if isinstance(r, dict)) if a
    ] if isinstance(raw_adjustments, list) else []
    return Settings(
        targets=targets,
        income_override=_number(raw.get("income_override")) or None,
        adjustments=adjustments,
    )


def save_settings(settings: Settings, path: Path = DEFAULT_PATH) -> None:
    """Write settings atomically: a crash mid-write leaves the old file intact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "targets": settings.targets,
        "income_override": settings.income_override,
        "adjustments": [a.to_dict() for a in settings.adjustments],
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
