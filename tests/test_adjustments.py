import io
from datetime import date

import pytest

from flowlens.adjustments import ACCOUNT, BIWEEKLY, MONTHLY, ONCE, Adjustment, occurrences, with_adjustments
from flowlens.calc import summarize
from flowlens.loader import load_transactions
from flowlens.sankey import build_sankey
from flowlens.settings import Settings, load_settings, save_settings

HEADER = "date,name,amount,type,category,account,excluded\n"


def frame(*lines: str):
    return load_transactions(io.StringIO(HEADER + "".join(l + "\n" for l in lines))).transactions


TXNS = (
    "2026-01-02,Pay,-1000,income,,Checking,true",
    "2026-01-05,Rent,800,regular,Rent,Card,false",
    "2026-03-31,Cafe,10,regular,Food,Card,false",
)


def test_biweekly_repeats_until_latest_transaction():
    adj = Adjustment("Big Mac", 95, BIWEEKLY, date(2026, 1, 16))
    dates = occurrences(adj, "2026-03-31")
    assert [d.strftime("%m-%d") for d in dates] == ["01-16", "01-30", "02-13", "02-27", "03-13", "03-27"]


def test_end_date_and_monthly():
    adj = Adjustment("Side", 50, MONTHLY, date(2026, 1, 31), end=date(2026, 3, 31))
    assert [d.strftime("%m-%d") for d in occurrences(adj, "2026-12-31")] == ["01-31", "02-28", "03-31"]


def test_adjustments_count_as_income_everywhere():
    df = with_adjustments(
        frame(*TXNS),
        [Adjustment("SoFi paychecks", 3000, ONCE, date(2026, 2, 1)), Adjustment("Big Mac", 100, BIWEEKLY, date(2026, 1, 16))],
    )
    s = summarize(df)
    assert s.income == pytest.approx(1000 + 3000 + 6 * 100)
    assert s.expenses == pytest.approx(810)  # adjustments never touch spending
    assert (df["account"] == ACCOUNT).sum() == 7
    names = build_sankey(df).names
    assert {"SoFi paychecks", "Big Mac", "Other income"} <= set(names)  # each is an income source


def test_no_adjustments_returns_same_frame():
    df = frame(*TXNS)
    assert with_adjustments(df, []) is df


@pytest.mark.parametrize(
    "raw",
    [
        {"name": "", "amount": 10, "repeats": ONCE, "start": "2026-01-01"},
        {"name": "x", "amount": 0, "repeats": ONCE, "start": "2026-01-01"},
        {"name": "x", "amount": 10, "repeats": "Weekly", "start": "2026-01-01"},
        {"name": "x", "amount": 10, "repeats": ONCE, "start": None},
        {"name": "x", "amount": "lots", "repeats": ONCE, "start": "2026-01-01"},
    ],
)
def test_incomplete_or_invalid_rows_are_rejected(raw):
    assert Adjustment.from_dict(raw) is None


def test_end_before_start_is_ignored():
    adj = Adjustment.from_dict({"name": "x", "amount": 5, "repeats": BIWEEKLY, "start": "2026-02-01", "end": "2026-01-01"})
    assert adj.end is None


def test_adjustments_saved_and_loaded(tmp_path):
    path = tmp_path / "settings.json"
    adj = [Adjustment("Big Mac", 95.5, BIWEEKLY, date(2026, 1, 16), end=date(2026, 5, 22))]
    save_settings(Settings(targets={"Rent": 30.0}, adjustments=adj), path)
    loaded = load_settings(path)
    assert loaded.adjustments == adj
    assert loaded.targets == {"Rent": 30.0}
