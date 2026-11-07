import io

import openpyxl
import pandas as pd
import pytest

from flowlens.calc import summarize
from flowlens.loader import load_transactions
from flowlens.payslips import (
    ACCOUNT,
    Columns,
    PayslipError,
    apply_payslips,
    guess_columns,
    guess_employer,
    parse_payslips,
    read_table,
)

HEADER = "date,name,amount,type,category,account,excluded\n"


def frame(*lines: str):
    return load_transactions(io.StringIO(HEADER + "".join(l + "\n" for l in lines))).transactions


def xlsx(rows) -> bytes:
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


WORKDAY_ROWS = [
    ["My Payslips"],  # title row above the header, as Workday exports often have
    [],
    ["Pay Period Start Date", "Pay Date", "Gross Pay", "Net Pay", "Net Pay YTD"],
    ["01/03/2026", "01/16/2026", "$4,000.00", "$2,750.50", "2750.50"],
    ["01/17/2026", "01/30/2026", "$4,000.00", "$2,749.25", "5499.75"],
    ["", "Total", "$8,000.00", "$5,499.75", ""],  # totals row must be ignored
]


def test_reads_xlsx_with_title_rows_and_guesses_columns():
    table = read_table(xlsx(WORKDAY_ROWS), "payslips.xlsx")
    cols = guess_columns(table)
    assert cols == Columns(date="Pay Date", net="Net Pay", gross="Gross Pay")
    p = parse_payslips(table, cols)
    assert list(p["date"].dt.strftime("%Y-%m-%d")) == ["2026-01-16", "2026-01-30"]
    assert list(p["net"]) == [2750.50, 2749.25]
    assert list(p["gross"]) == [4000.0, 4000.0]


def test_reads_csv():
    data = b"Check Date,Net Amount\n2026-02-13,\"2,800.00\"\n"
    table = read_table(data, "pay.csv")
    p = parse_payslips(table, guess_columns(table))
    assert p.iloc[0]["net"] == 2800.0


def test_no_header_row_is_an_error():
    with pytest.raises(PayslipError):
        read_table(b"a,b\n1,2\n", "x.csv")


def test_payslips_replace_paycheck_deposits_inside_their_range_only():
    txns = frame(
        "2025-12-19,Fidelity Technol,-250,income,,Checking,true",  # before payslips: kept
        "2026-01-16,Fidelity Technol,-250,income,,Checking,true",  # replaced
        "2026-01-17,Fidelity Technologies Corporation,-2000,income,,Robinhood,true",  # replaced (window)
        "2026-01-20,Interest Earned,-1.50,income,,Savings,false",  # not a paycheck: kept
        "2026-01-21,Rent,900,regular,Rent,Card,false",
    )
    table = read_table(xlsx(WORKDAY_ROWS), "payslips.xlsx")
    payslips = parse_payslips(table, guess_columns(table))
    assert guess_employer(txns) == "Fidelity"
    out, replaced = apply_payslips(txns, payslips, "Fidelity")
    assert replaced == 2
    assert summarize(out).income == pytest.approx(250 + 1.50 + 2750.50 + 2749.25)
    assert summarize(out).expenses == pytest.approx(900)
    assert (out["account"] == ACCOUNT).sum() == 2


def test_blank_employer_replaces_nothing():
    txns = frame("2026-01-16,Fidelity,-250,income,,Checking,true")
    payslips = pd.DataFrame({"date": [pd.Timestamp("2026-01-16")], "net": [2750.0]})
    out, replaced = apply_payslips(txns, payslips, "  ")
    assert replaced == 0 and len(out) == 2
