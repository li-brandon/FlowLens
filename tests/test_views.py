import io

import pandas as pd
import pytest

from flowlens.dates import ALL_TIME, PRESETS, filter_range, preset_range
from flowlens.drilldown import category_detail
from flowlens.loader import load_transactions
from flowlens.sankey import build_sankey

HEADER = "date,name,amount,type,category,account,excluded\n"


def frame(*lines: str):
    return load_transactions(io.StringIO(HEADER + "".join(l + "\n" for l in lines))).transactions


# --- dates -----------------------------------------------------------------


def test_presets_match_ticket():
    assert PRESETS == ("Last Week", "Last Month", "60 Days", "90 Days", "6 Months", "Year", "All Time")


@pytest.mark.parametrize(
    "preset,start",
    [
        ("Last Week", "2026-10-25"),
        ("Last Month", "2026-10-01"),
        ("60 Days", "2026-09-02"),
        ("90 Days", "2026-08-03"),
        ("6 Months", "2026-05-01"),
        ("Year", "2025-11-01"),
    ],
)
def test_preset_ranges_end_on_latest_transaction(preset, start):
    dates = pd.Series(pd.to_datetime(["2020-01-01", "2026-10-31"]))
    assert preset_range(preset, dates) == (pd.Timestamp(start), pd.Timestamp("2026-10-31"))


def test_preset_clamped_to_first_transaction():
    dates = pd.Series(pd.to_datetime(["2026-10-20", "2026-10-31"]))
    assert preset_range("Year", dates)[0] == pd.Timestamp("2026-10-20")


def test_all_time_spans_data():
    dates = pd.Series(pd.to_datetime(["2026-02-03", "2026-10-31"]))
    assert preset_range(ALL_TIME, dates) == (pd.Timestamp("2026-02-03"), pd.Timestamp("2026-10-31"))


def test_filter_range_inclusive_and_order_insensitive():
    df = frame(
        "2026-01-01,A,1,regular,X,a,false",
        "2026-01-02,B,1,regular,X,a,false",
        "2026-01-03,C,1,regular,X,a,false",
    )
    assert list(filter_range(df, "2026-01-02", "2026-01-03")["name"]) == ["B", "C"]
    assert list(filter_range(df, "2026-01-03", "2026-01-02")["name"]) == ["B", "C"]


# --- sankey ----------------------------------------------------------------


def flows(data):
    return {(data.labels[s].split(" ")[0], data.labels[t].split(" ")[0]): v for s, t, v in zip(data.sources, data.targets, data.values)}


def test_sankey_income_to_categories_and_savings():
    df = frame(
        "2026-01-01,Pay,-1000,income,Paycheck,a,false",
        "2026-01-02,Rent,600,regular,Rent,a,false",
        "2026-01-03,Food,150,regular,Food,a,false",
    )
    data = build_sankey(df)
    f = flows(data)
    assert f[("Income", "Rent")] == pytest.approx(600)
    assert f[("Income", "Food")] == pytest.approx(150)
    assert f[("Income", "Savings")] == pytest.approx(250)
    assert data.overspent == 0
    assert any("60.0% of income" in l for l in data.labels)
    assert any(l.startswith("Savings") and "25.0% of income" in l for l in data.labels)


def test_sankey_overspending_adds_shortfall_node_and_balances():
    df = frame(
        "2026-01-01,Pay,-500,income,Paycheck,a,false",
        "2026-01-02,Rent,600,regular,Rent,a,false",
        "2026-01-03,Food,200,regular,Food,a,false",
    )
    data = build_sankey(df)
    assert data.overspent == pytest.approx(300)
    assert not any(l.startswith("Savings") for l in data.labels)
    f = flows(data)
    assert f[("Income", "Rent")] + f[("Overspent", "Rent")] == pytest.approx(600)
    income_out = sum(v for (s, _), v in f.items() if s == "Income")
    assert income_out == pytest.approx(500)


def test_sankey_no_income_only_shortfall():
    data = build_sankey(frame("2026-01-02,Food,20,regular,Food,a,false"))
    assert data.overspent == pytest.approx(20)
    assert any("no income" in l for l in data.labels)


def test_sankey_empty():
    assert build_sankey(frame()).is_empty


def test_sankey_skips_net_negative_category():
    df = frame(
        "2026-01-01,Pay,-100,income,Paycheck,a,false",
        "2026-01-02,Shop,-30,regular,Shopping,a,false",
    )
    data = build_sankey(df)
    assert not any(l.startswith("Shopping") for l in data.labels)


# --- drill-down ------------------------------------------------------------


def test_category_detail_metrics_merchants_and_order():
    lines = [f"2026-01-{d:02d},Shop{d},{d * 10},regular,Shopping,a,false" for d in range(1, 13)]
    lines += [
        "2026-01-20,Shop1,-5,regular,Shopping,a,false",
        "2026-01-21,Other,99,regular,Food,a,false",
        "2026-01-22,Excluded,500,regular,Shopping,a,true",
    ]
    detail = category_detail(frame(*lines), "Shopping")
    assert detail.count == 13
    assert detail.total == pytest.approx(sum(d * 10 for d in range(1, 13)) - 5)
    assert detail.average == pytest.approx(detail.total / 13)
    assert len(detail.top_merchants) == 10
    assert detail.top_merchants.index[0] == "Shop12"
    assert detail.transactions["date"].is_monotonic_decreasing
    assert "Excluded" not in set(detail.transactions["name"])


def test_category_detail_unknown_category():
    detail = category_detail(frame("2026-01-01,A,1,regular,X,a,false"), "Nope")
    assert (detail.count, detail.total, detail.average) == (0, 0, 0)
