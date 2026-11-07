import io
from pathlib import Path

import pandas as pd
import pytest

from flowlens.loader import CsvFormatError, load_transactions

HEADER = "date,name,amount,type,category,account,excluded\n"
SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_transactions.csv"


def load(text: str):
    return load_transactions(io.StringIO(text))


def test_loads_all_rows_of_sample_file():
    result = load_transactions(SAMPLE)
    expected = sum(1 for _ in SAMPLE.open()) - 1
    assert len(result.transactions) == expected
    assert result.bad_rows.empty


def test_parses_typed_values():
    result = load(HEADER + '2026-01-05, Cafe ,"$1,234.50",Regular,Food,Card,TRUE\n')
    row = result.transactions.iloc[0]
    assert row["date"] == pd.Timestamp("2026-01-05")
    assert row["amount"] == pytest.approx(1234.50)
    assert row["name"] == "Cafe"
    assert row["type"] == "regular"
    assert bool(row["excluded"])


def test_parenthesized_amount_is_negative():
    result = load(HEADER + "2026-01-05,Store,(20.00),regular,Shopping,Card,false\n")
    assert result.transactions.iloc[0]["amount"] == pytest.approx(-20.0)


def test_missing_columns_named_in_error():
    with pytest.raises(CsvFormatError) as exc:
        load("date,name,amount\n2026-01-01,x,1\n")
    msg = str(exc.value)
    for col in ("type", "category", "account", "excluded"):
        assert col in msg


def test_column_names_are_case_and_space_insensitive():
    result = load(" Date ,NAME,Amount,Type,Category,Account,Excluded\n2026-01-01,x,1,regular,A,B,false\n")
    assert len(result.transactions) == 1


def test_empty_file_raises_clear_error():
    with pytest.raises(CsvFormatError, match="empty"):
        load("")


def test_bad_rows_are_reported_not_dropped_silently():
    text = HEADER + (
        "2026-01-01,Good,10,regular,Food,Card,false\n"
        "not-a-date,BadDate,10,regular,Food,Card,false\n"
        "2026-01-03,BadAmount,ten,regular,Food,Card,false\n"
        "nope,BadBoth,??,regular,Food,Card,maybe\n"
    )
    result = load(text)
    assert list(result.transactions["name"]) == ["Good"]
    bad = result.bad_rows.set_index("row")["reason"].to_dict()
    assert bad[3] == "unreadable date"
    assert bad[4] == "unreadable amount"
    assert bad[5] == "unreadable date; unreadable amount; unreadable excluded flag"


def test_blank_category_becomes_other():
    result = load(HEADER + "2026-01-01,Mystery,5,regular,,Card,false\n")
    assert result.transactions.iloc[0]["category"] == "Other"


def test_blank_excluded_means_not_excluded():
    result = load(HEADER + "2026-01-01,Shop,5,regular,Food,Card,\n")
    assert not result.transactions.iloc[0]["excluded"]


def test_extra_columns_are_kept():
    result = load("date,name,amount,type,category,account,excluded,tags\n2026-01-01,x,1,regular,A,B,false,trip\n")
    assert result.transactions.iloc[0]["tags"] == "trip"


def test_blank_income_category_is_kept_apart_from_spending_other():
    result = load(HEADER + "2026-01-01,Pay,-5,income,,Card,true\n2026-01-02,Odd,5,regular,,Card,false\n")
    assert list(result.transactions["category"]) == ["Other income", "Other"]
