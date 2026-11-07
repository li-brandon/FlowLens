import io
import json

import pytest

from flowlens.loader import load_transactions
from flowlens.projections import DAYS_PER_MONTH, ON_PACE, OVER, months_in_range, project
from flowlens.settings import Settings, load_settings, save_settings

HEADER = "date,name,amount,type,category,account,excluded\n"


def frame(*lines: str):
    return load_transactions(io.StringIO(HEADER + "".join(l + "\n" for l in lines))).transactions


def row(table, category):
    return table.set_index("category").loc[category]


# --- projection math --------------------------------------------------------


def test_months_in_range_is_inclusive():
    assert months_in_range("2026-01-01", "2026-01-01") == pytest.approx(1 / DAYS_PER_MONTH)
    assert months_in_range("2026-01-01", "2026-12-31") == pytest.approx(365 / DAYS_PER_MONTH)


def test_two_months_of_spend_projects_to_a_year():
    df = frame(
        "2026-01-05,Shop,100,regular,Groceries,A,false",
        "2026-02-05,Shop,150,regular,Groceries,A,false",
        "2026-02-10,Shop,-50,regular,Groceries,A,false",  # refund nets out
    )
    p = project(df, "2026-01-01", "2026-02-28")
    months = 59 / DAYS_PER_MONTH
    g = row(p.table, "Groceries")
    assert g["spent"] == pytest.approx(200)
    assert g["monthly"] == pytest.approx(200 / months)
    assert g["projected"] == pytest.approx(200 / months * 12)


def test_income_detected_and_override_wins():
    df = frame(
        "2026-01-15,Pay,-6000,income,Paycheck,A,false",
        "2026-01-20,Rent,1500,regular,Rent,A,false",
    )
    start, end = "2026-01-01", "2026-01-31"
    detected = 6000 / (31 / DAYS_PER_MONTH) * 12
    assert project(df, start, end).annual_income == pytest.approx(detected)

    p = project(df, start, end, income_override=100_000)
    assert p.detected_income == pytest.approx(detected)
    assert p.annual_income == 100_000
    assert row(p.table, "Rent")["pct_of_income"] == pytest.approx(row(p.table, "Rent")["projected"] / 1000)


def test_target_status_on_pace_over_and_unset():
    df = frame(
        "2026-01-20,Rent,1000,regular,Rent,A,false",
        "2026-01-21,Cafe,500,regular,Food,A,false",
        "2026-01-22,Bus,10,regular,Transport,A,false",
    )
    # Override 120k/yr on a 12-month range keeps the numbers easy: projected = spent.
    p = project(df, "2025-02-01", "2026-01-31", targets={"Rent": 1, "Food": 0.4}, income_override=120_000)
    assert row(p.table, "Rent")["target_amount"] == pytest.approx(1200)
    assert row(p.table, "Rent")["status"] == ON_PACE  # ~1000 <= 1200
    assert row(p.table, "Food")["status"] == OVER  # ~500 > 480
    assert row(p.table, "Transport")["status"] == ""


def test_no_income_means_any_target_is_over():
    df = frame("2026-01-20,Rent,1000,regular,Rent,A,false")
    p = project(df, "2026-01-01", "2026-01-31", targets={"Rent": 30})
    r = row(p.table, "Rent")
    assert p.annual_income == 0
    assert r["pct_of_income"] is None
    assert r["status"] == OVER


def test_net_refund_category_projects_to_zero():
    df = frame(
        "2026-01-05,Store,20,regular,Shopping,A,false",
        "2026-01-06,Store,-80,regular,Shopping,A,false",
    )
    assert row(project(df, "2026-01-01", "2026-01-31").table, "Shopping")["projected"] == 0


def test_empty_range_gives_empty_table():
    p = project(frame("2026-01-15,Pay,-100,income,Pay,A,false").iloc[0:0], "2026-01-01", "2026-01-31")
    assert p.table.empty and p.annual_income == 0


# --- saved settings ---------------------------------------------------------


def test_settings_round_trip(tmp_path):
    path = tmp_path / "nested" / "settings.json"
    assert load_settings(path) == Settings()
    save_settings(Settings(targets={"Rent": 30.0, "Food": 12.5}, income_override=90_000), path)
    loaded = load_settings(path)
    assert loaded.targets == {"Rent": 30.0, "Food": 12.5}
    assert loaded.income_override == 90_000
    assert not (tmp_path / "nested" / "settings.json.tmp").exists()


def test_bad_values_are_dropped(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"targets": {"Rent": 30, "Bad": "x", "Neg": -1, "Flag": True}, "income_override": 0}))
    loaded = load_settings(path)
    assert loaded.targets == {"Rent": 30.0}
    assert loaded.income_override is None


def test_corrupt_file_is_moved_aside_not_lost(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    loaded = load_settings(path)
    assert loaded == Settings(warning=loaded.warning)
    assert loaded.warning
    assert not path.exists()
    assert (tmp_path / "settings.json.bad").read_text() == "{not json"
