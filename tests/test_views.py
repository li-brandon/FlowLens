import io

import pandas as pd
import pytest

from flowlens.dates import ALL_TIME, PRESETS, filter_range, preset_range
from flowlens.drilldown import category_detail
from flowlens.loader import load_transactions
from flowlens.sankey import build_sankey, color_keys, figure_height, has_groups, node_positions

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

GROUPED_HEADER = "date,name,amount,type,category,parent category,account,excluded\n"


def grouped(*lines: str):
    return load_transactions(io.StringIO(GROUPED_HEADER + "".join(l + "\n" for l in lines))).transactions


def flows(data):
    return {(data.names[s], data.names[t]): v for s, t, v in zip(data.sources, data.targets, data.values)}


def test_sankey_income_to_categories_and_savings():
    df = frame(
        "2026-01-01,Pay,-1000,income,Paycheck,a,false",
        "2026-01-02,Rent,600,regular,Rent,a,false",
        "2026-01-03,Food,150,regular,Food,a,false",
    )
    data = build_sankey(df)
    f = flows(data)
    assert "Paycheck" not in data.names  # one source would only repeat Income
    assert f[("Income", "Rent")] == pytest.approx(600)
    assert f[("Income", "Food")] == pytest.approx(150)
    assert f[("Income", "Savings")] == pytest.approx(250)
    assert data.overspent == 0
    assert "Rent<br><b>$600.00 (60.0%)</b>" in data.labels
    assert "Savings<br><b>$250.00 (25.0%)</b>" in data.labels


def test_sankey_overspending_adds_shortfall_node_and_balances():
    df = frame(
        "2026-01-01,Pay,-500,income,Paycheck,a,false",
        "2026-01-02,Rent,600,regular,Rent,a,false",
        "2026-01-03,Food,200,regular,Food,a,false",
    )
    data = build_sankey(df)
    assert data.overspent == pytest.approx(300)
    assert "Savings" not in data.names
    f = flows(data)
    assert f[("Income", "Rent")] + f[("Overspent", "Rent")] == pytest.approx(600)
    income_out = sum(v for (s, _), v in f.items() if s == "Income")
    assert income_out == pytest.approx(500)


def test_sankey_no_income_only_shortfall():
    data = build_sankey(frame("2026-01-02,Food,20,regular,Food,a,false"))
    assert data.overspent == pytest.approx(20)
    assert "Income" not in data.names
    assert "Food<br><b>$20.00</b>" in data.labels  # no % without income


def test_sankey_empty():
    assert build_sankey(frame()).is_empty


def test_sankey_skips_net_negative_category():
    df = frame(
        "2026-01-01,Pay,-100,income,Paycheck,a,false",
        "2026-01-02,Shop,-30,regular,Shopping,a,false",
    )
    assert "Shopping" not in build_sankey(df).names


GROUPED_ROWS = (
    "2026-01-01,Pay,-1000,income,Paycheck,Income,a,false",
    "2026-01-02,Rent,500,regular,Rent,Housing,a,false",
    "2026-01-03,Power,100,regular,Utilities,Housing,a,false",
    "2026-01-04,Cafe,150,regular,Coffee,Food & Dining,a,false",
    "2026-01-05,Store,50,regular,Groceries,Food & Dining,a,false",
    "2026-01-06,Store,-80,regular,Groceries,Food & Dining,a,false",  # net-negative: dropped
)


def test_sankey_group_view():
    data = build_sankey(grouped(*GROUPED_ROWS), "Group")
    f = flows(data)
    assert "Paycheck" not in data.names  # Group view starts at Income
    assert f[("Income", "Housing")] == pytest.approx(600)
    assert f[("Income", "Food & Dining")] == pytest.approx(150)
    assert f[("Income", "Savings")] == pytest.approx(250)
    assert "Rent" not in data.names


def test_sankey_both_view_links_groups_to_categories():
    data = build_sankey(grouped(*GROUPED_ROWS, "2026-01-07,Gig,-200,income,,,a,true"), "Both")
    f = flows(data)
    assert f[("Paycheck", "Income")] == pytest.approx(1000)
    assert f[("Other income", "Income")] == pytest.approx(200)  # blank + excluded income still counts
    assert f[("Income", "Housing")] == pytest.approx(600)
    assert "Other" not in data.names
    assert f[("Housing", "Rent")] == pytest.approx(500)
    assert f[("Housing", "Utilities")] == pytest.approx(100)
    assert f[("Food & Dining", "Coffee")] == pytest.approx(150)
    assert "Groceries" not in data.names
    # Every flow out of a group equals the group's flow in.
    for g in ("Housing", "Food & Dining"):
        assert sum(v for (s, _), v in f.items() if s == g) == pytest.approx(f[("Income", g)])


def test_sankey_columns_and_largest_first():
    data = build_sankey(grouped(*GROUPED_ROWS, "2026-01-07,Gig,-200,income,Side,Income,a,false"), "Both")
    x, y = node_positions(data, figure_height(data))
    pos = dict(zip(data.names, zip(x, y)))
    assert pos["Paycheck"][0] < pos["Income"][0] < pos["Housing"][0] < pos["Rent"][0]
    assert pos["Housing"][1] < pos["Food & Dining"][1]  # bigger group above
    assert pos["Rent"][1] < pos["Utilities"][1] < pos["Coffee"][1]  # grouped, largest first


def test_sankey_without_group_column_falls_back_to_category():
    df = frame("2026-01-01,Pay,-100,income,Paycheck,a,false", "2026-01-02,Rent,60,regular,Rent,a,false")
    assert not has_groups(df)
    assert flows(build_sankey(df, "Both")) == flows(build_sankey(df, "Category"))


def test_sankey_colors_follow_the_group_not_the_rank():
    df = grouped(*GROUPED_ROWS)
    keys = color_keys(df)
    both = build_sankey(df, "Both", keys=keys)
    color = dict(zip(both.names, both.colors))
    assert color["Rent"] == color["Utilities"] == color["Housing"]
    # Filtering to Housing only must not repaint it.
    only_housing = build_sankey(df[df["group"] != "Food & Dining"], "Group", keys=keys)
    assert dict(zip(only_housing.names, only_housing.colors))["Housing"] == color["Housing"]


def test_blank_parent_category_means_own_group():
    df = grouped("2026-01-02,Gym,40,regular,Fitness,,a,false")
    assert df.iloc[0]["group"] == "Fitness"


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


# --- hiding Income / Overspent ----------------------------------------------

OVERSPENT_ROWS = (
    "2026-01-01,Pay,-500,income,Paycheck,Income,a,false",
    "2026-01-02,Rent,600,regular,Rent,Housing,a,false",
    "2026-01-03,Cafe,200,regular,Coffee,Food & Dining,a,false",
)


def test_hide_overspent_income_feeds_categories_in_full():
    data = build_sankey(grouped(*OVERSPENT_ROWS), "Group", show_overspent=False)
    f = flows(data)
    assert "Overspent" not in data.names
    assert f[("Income", "Housing")] == pytest.approx(600)
    assert f[("Income", "Food & Dining")] == pytest.approx(200)
    assert data.overspent == pytest.approx(300)  # still reported for the warning


def test_hide_income_starts_from_spending():
    data = build_sankey(grouped(*OVERSPENT_ROWS), "Both", show_income=False)
    f = flows(data)
    assert not {"Income", "Overspent", "Savings", "Paycheck"} & set(data.names)
    assert f[("Spending", "Housing")] == pytest.approx(600)
    assert f[("Housing", "Rent")] == pytest.approx(600)
    assert "Spending<br><b>$800.00 (160.0%)</b>" in data.labels


def test_hide_both_with_no_income_still_shows_spending():
    data = build_sankey(frame("2026-01-02,Food,20,regular,Food,a,false"), show_overspent=False)
    assert flows(data) == {("Spending", "Food"): pytest.approx(20)}


def test_hide_income_with_no_spending_is_empty():
    assert build_sankey(frame("2026-01-01,Pay,-100,income,Paycheck,a,false"), show_income=False).is_empty
