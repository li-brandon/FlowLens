import io
from pathlib import Path

import pytest

from flowlens.calc import category_totals, summarize
from flowlens.loader import UNCATEGORIZED, load_transactions

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "calc_cases.csv"
HEADER = "date,name,amount,type,category,account,excluded\n"


def frame(*lines: str):
    return load_transactions(io.StringIO(HEADER + "".join(l + "\n" for l in lines))).transactions


def test_fixture_totals():
    # Fixture: income 5000 (4000 + 1000 excluded-but-counted)
    # Groceries 300 - 50 refund = 250, Rent 1500, Uncategorized 20
    # Ignored: 999 excluded dinner, 700 transfer.
    s = summarize(load_transactions(FIXTURE).transactions)
    assert s.income == pytest.approx(5000)
    assert s.expenses == pytest.approx(1770)
    assert s.savings == pytest.approx(3230)
    assert s.savings_rate == pytest.approx(64.6)


def test_income_uses_absolute_value():
    df = frame("2026-01-01,Pay,-2000,income,Paycheck,A,false", "2026-01-02,Bonus,500,income,Paycheck,A,false")
    assert summarize(df).income == pytest.approx(2500)


def test_refund_reduces_category_total():
    df = frame(
        "2026-01-01,Shop,100,regular,Shopping,A,false",
        "2026-01-02,Shop,-30,regular,Shopping,A,false",
    )
    assert category_totals(df)["Shopping"] == pytest.approx(70)
    assert summarize(df).expenses == pytest.approx(70)


def test_excluded_rows_dropped_from_expenses_but_income_kept():
    df = frame(
        "2026-01-01,Pay,-1000,income,Paycheck,A,true",
        "2026-01-02,Dinner,200,regular,Food,A,true",
        "2026-01-03,Lunch,15,regular,Food,A,false",
    )
    s = summarize(df)
    assert s.income == pytest.approx(1000)
    assert s.expenses == pytest.approx(15)


def test_transfers_excluded_from_expenses():
    df = frame(
        "2026-01-01,To savings,500,internal transfer,Transfer,A,false",
        "2026-01-02,Card payment,300,transfer,Transfer,A,false",
        "2026-01-03,Lunch,15,regular,Food,A,false",
    )
    assert summarize(df).expenses == pytest.approx(15)
    assert "Transfer" not in category_totals(df)


def test_empty_category_counted_as_uncategorized():
    df = frame("2026-01-01,Mystery,42,regular,,A,false")
    assert category_totals(df)[UNCATEGORIZED] == pytest.approx(42)


def test_zero_income_has_no_savings_rate():
    df = frame("2026-01-01,Lunch,15,regular,Food,A,false")
    s = summarize(df)
    assert s.income == 0
    assert s.savings == pytest.approx(-15)
    assert s.savings_rate is None


def test_empty_frame():
    df = frame()
    s = summarize(df)
    assert (s.income, s.expenses, s.savings, s.savings_rate) == (0, 0, 0, None)
    assert category_totals(df).empty


def test_overspending_gives_negative_rate():
    df = frame("2026-01-01,Pay,-100,income,Paycheck,A,false", "2026-01-02,TV,150,regular,Shopping,A,false")
    s = summarize(df)
    assert s.savings == pytest.approx(-50)
    assert s.savings_rate == pytest.approx(-50)


def test_category_totals_sorted_descending():
    df = frame(
        "2026-01-01,A,10,regular,Small,A,false",
        "2026-01-01,B,90,regular,Big,A,false",
        "2026-01-01,C,40,regular,Mid,A,false",
    )
    assert list(category_totals(df).index) == ["Big", "Mid", "Small"]
