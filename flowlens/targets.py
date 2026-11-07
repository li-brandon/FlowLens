"""Save per-category targets locally so they survive an app restart.

Targets are stored as JSON (``{"version": 1, "targets": {"Groceries": 10.0, ...}}``) in
``~/.flowlens/targets.json``, outside the repo so they can't be committed by accident.
Set ``FLOWLENS_TARGETS_PATH`` to use a different file.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

ENV_VAR = "FLOWLENS_TARGETS_PATH"
_VERSION = 1


def default_path() -> Path:
    override = os.environ.get(ENV_VAR)
    return Path(override).expanduser() if override else Path.home() / ".flowlens" / "targets.json"


def clean_targets(raw: dict) -> dict[str, float]:
    """Keep only valid entries: non-empty category name -> finite percent in [0, 100]."""
    out: dict[str, float] = {}
    for category, pct in raw.items():
        if not isinstance(category, str) or not category.strip():
            continue
        if isinstance(pct, bool):
            continue
        try:
            value = float(pct)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and 0 <= value <= 100:
            out[category] = value
    return out


def load_targets(path: Path | None = None) -> dict[str, float]:
    """Saved targets, or ``{}`` when the file is missing or unreadable."""
    path = path or default_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or not isinstance(data.get("targets"), dict):
        return {}
    return clean_targets(data["targets"])


def save_targets(targets: dict[str, float], path: Path | None = None) -> Path:
    """Write targets atomically (temp file + rename) and return the path used."""
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": _VERSION, "targets": dict(sorted(clean_targets(targets).items()))}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def merge_targets(saved: dict[str, float], edited: dict[str, float | None]) -> dict[str, float]:
    """Apply edits to saved targets. ``None`` (a cleared cell) removes that target.

    Categories not in ``edited`` keep their saved target, so a target for a category that
    isn't in the current date range isn't lost.
    """
    merged = dict(saved)
    for category, pct in edited.items():
        if pct is None or (isinstance(pct, float) and math.isnan(pct)):
            merged.pop(category, None)
        else:
            merged[category] = pct
    return clean_targets(merged)
