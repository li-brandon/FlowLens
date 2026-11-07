import io
import json
import math

import pytest

from flowlens.loader import load_transactions
from flowlens.projections import (
    DAYS_PER_MONTH,
    NO_INCOME,
    NO_TARGET,
    ON_PACE,
    OVER,
    annualize,
    detected_annual_income,
    months_in_range,
    project_categories,
    target_status,
)
from flowlens.targets import clean_targets, load_targets, merge_targets, save_targets

HEADER = "date,name,amount,type,category,account,excluded\n"


def frame(*lines: str):
    return load_transactions(io.StringIO(HEADER + "".join(l + "\n" for l in lines))).transactions


# --- projection math -------------------------------------------------------


def test_months_in_range_is_inclusive_and_order_insensitive():
    assert months_in_range("2026-01-01", "2026-01-01") == pytest.approx(1 / DAYS_PER_MONTH)
    assert months_in_range("2026-01-01", "2026-12-31") == pytest.approx(365 / DAYS_PER_MONTH)
    assert months_in_range("2026-03-31", "2026-01-01") == months_in_range("2026-01-01", "2026-03-31")


def test_full_year_window_projects_close_to_actual():
    # 365 days is ~11.99 months, so annualizing barely changes the total.
    assert annualize(1200, months_in_range("2025-01-01", "2025-12-31")) == pytest.approx(1200 * 365.25 / 365)


def test_annualize_zero_months():
    assert annualize(100, 0) == 0


def test_project_categories_monthly_average_and_annual():
    df = frame(
        "2026-01-01,Pay,-3000,income,Paycheck,a,false",
        "2026-01-05,Market,300,regular,Groceries,a,false",
        "2026-01-20,Market,-50,regular,Groceries,a,false",  # refund
        "2026-01-10,Landlord,1500,regular,Rent,a,false",
        "2026-01-11,Excluded,999,regular,Rent,a,true",
        "2026-01-12,To savings,700,internal transfer,Transfer,a,false",
    )
    start, end = "2026-01-01", "2026-01-31"
    months = 31 / DAYS_PER_MONTH
    income = detected_annual_income(df, start, end)
    assert income == pytest.approx(3000 / months * 12)

    out = project_categories(df, start, end, income)
    assert list(out["category"]) == ["Rent", "Groceries"]  # largest projection first
    groceries = out.set_index("category").loc["Groceries"]
    assert groceries["spent"] == pytest.approx(250)
    assert groceries["monthly_avg"] == pytest.approx(250 / months)
    assert groceries["projected_annual"] == pytest.approx(250 / months * 12)
    assert math.isnan(groceries["target_pct"]) and math.isnan(groceries["target_amount"])
    assert groceries["status"] == NO_TARGET


def test_targets_on_pace_and_over():
    df = frame(
        "2026-01-01,Pay,-1000,income,Paycheck,a,false",
        "2026-01-02,Landlord,400,regular,Rent,a,false",
        "2026-01-03,Market,100,regular,Groceries,a,false",
    )
    start, end = "2026-01-01", "2026-01-31"
    income = detected_annual_income(df, start, end)  # rent is 40% of it, groceries 10%
    out = project_categories(df, start, end, income, {"Rent": 35, "Groceries": 10}).set_index("category")
    assert out.loc["Rent", "status"] == OVER
    assert out.loc["Rent", "target_amount"] == pytest.approx(0.35 * income)
    assert out.loc["Groceries", "status"] == ON_PACE  # exactly at target counts as on pace


def test_manual_income_override_changes_status():
    df = frame("2026-01-02,Landlord,400,regular,Rent,a,false")  # no income in CSV
    start, end = "2026-01-01", "2026-01-31"
    assert detected_annual_income(df, start, end) == 0
    assert project_categories(df, start, end, 0, {"Rent": 30}).loc[0, "status"] == NO_INCOME
    projected = project_categories(df, start, end, 0).loc[0, "projected_annual"]
    assert project_categories(df, start, end, projected * 2, {"Rent": 30}).loc[0, "status"] == OVER
    assert project_categories(df, start, end, projected * 4, {"Rent": 30}).loc[0, "status"] == ON_PACE


def test_target_status_rules():
    assert target_status(100, None, 1000) == NO_TARGET
    assert target_status(100, 10, 0) == NO_INCOME
    assert target_status(100, 10, 1000) == ON_PACE
    assert target_status(100.01, 10, 1000) == OVER


def test_project_categories_empty():
    out = project_categories(frame(), "2026-01-01", "2026-01-31", 0)
    assert out.empty and "status" in out.columns


# --- saved targets ---------------------------------------------------------


def test_targets_round_trip(tmp_path):
    path = tmp_path / "nested" / "targets.json"
    save_targets({"Rent": 30, "Groceries": 12.5}, path)
    assert load_targets(path) == {"Rent": 30.0, "Groceries": 12.5}
    assert json.loads(path.read_text())["version"] == 1
    assert not path.with_name("targets.json.tmp").exists()


def test_load_targets_missing_or_corrupt_file(tmp_path):
    assert load_targets(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert load_targets(bad) == {}
    bad.write_text('["a list"]')
    assert load_targets(bad) == {}


def test_default_path_env_override(tmp_path, monkeypatch):
    path = tmp_path / "t.json"
    monkeypatch.setenv("FLOWLENS_TARGETS_PATH", str(path))
    save_targets({"Rent": 25})
    assert path.exists() and load_targets() == {"Rent": 25.0}


def test_clean_targets_drops_invalid_entries():
    raw = {"Rent": 30, "Neg": -1, "Big": 101, "Nan": float("nan"), "Str": "x", "Bool": True, "": 5, "Ok": "12"}
    assert clean_targets(raw) == {"Rent": 30.0, "Ok": 12.0}


def test_merge_targets_keeps_unedited_and_clears_blank():
    saved = {"Rent": 30.0, "Travel": 5.0, "Groceries": 10.0}
    merged = merge_targets(saved, {"Rent": 25.0, "Groceries": None, "Food": float("nan"), "Gas": 3.0})
    assert merged == {"Rent": 25.0, "Travel": 5.0, "Gas": 3.0}
