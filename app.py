"""FlowLens: local-only cash-flow visualizer.

Run with:  uv run streamlit run app.py
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from flowlens.calc import category_totals, summarize
from flowlens.dates import CUSTOM, PRESETS, filter_range, preset_range
from flowlens.drilldown import category_detail
from flowlens.loader import CsvFormatError, LoadResult, load_transactions
from flowlens.sankey import build_sankey, sankey_figure

SAMPLE_PATH = Path(__file__).parent / "samples" / "sample_transactions.csv"

st.set_page_config(page_title="FlowLens", page_icon="💸", layout="wide")


@st.cache_data(show_spinner=False)
def _load(data: bytes) -> LoadResult:
    return load_transactions(io.BytesIO(data))


def money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


# --- Sidebar: data source and date range ------------------------------------

with st.sidebar:
    st.title("FlowLens")
    st.caption("Your CSV stays on this computer. Nothing is uploaded anywhere.")
    upload = st.file_uploader("Transaction CSV (Copilot Money export)", type=["csv"])
    use_sample = st.checkbox("Use sample data (fake)", value=upload is None)

if upload is not None and not use_sample:
    raw_bytes, source_name = upload.getvalue(), upload.name
elif use_sample:
    raw_bytes, source_name = SAMPLE_PATH.read_bytes(), "sample data"
else:
    st.title("FlowLens")
    st.info("Upload a transaction CSV in the sidebar, or tick **Use sample data** to explore.")
    st.stop()

try:
    result = _load(raw_bytes)
except CsvFormatError as exc:
    st.error(f"Couldn't load **{source_name}**: {exc}")
    st.caption("Required columns: date, name, amount, type, category, account, excluded.")
    st.stop()

txns = result.transactions
if not result.bad_rows.empty:
    with st.expander(f"⚠️ {len(result.bad_rows)} row(s) couldn't be read and were skipped", expanded=False):
        st.dataframe(result.bad_rows, hide_index=True, width="stretch")

if txns.empty:
    st.warning("No readable transactions in this file.")
    st.stop()

with st.sidebar:
    st.divider()
    choice = st.radio("Date range", [*PRESETS, CUSTOM], index=PRESETS.index("6 Months"))
    first, last = txns["date"].min().date(), txns["date"].max().date()
    if choice == CUSTOM:
        picked = st.date_input("Start / end", value=(first, last), min_value=first, max_value=last)
        if isinstance(picked, (tuple, list)) and len(picked) == 2:
            start, end = picked
        else:  # user has only clicked the start date so far
            start = end = picked[0] if isinstance(picked, (tuple, list)) else picked
    else:
        start, end = (d.date() for d in preset_range(choice, txns["date"]))
    st.caption(f"{start:%b %d, %Y} → {end:%b %d, %Y}")

view = filter_range(txns, start, end)

# --- Header metrics ---------------------------------------------------------

st.title("Cash flow")
st.caption(f"{source_name} · {len(view):,} transactions in range")

s = summarize(view)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Income", money(s.income))
c2.metric("Expenses", money(s.expenses))
c3.metric("Savings", money(s.savings))
c4.metric("Savings rate", "n/a" if s.savings_rate is None else f"{s.savings_rate:.1f}%")

tab_flow, tab_drill = st.tabs(["Flow", "Category drill-down"])

# --- Sankey -----------------------------------------------------------------

with tab_flow:
    data = build_sankey(view)
    if data.is_empty:
        st.info("No income or spending in this date range.")
    else:
        if data.overspent > 0:
            st.warning(
                f"Spending exceeded income by **{money(data.overspent)}** in this range. "
                "The red **Overspent** node shows the gap."
            )
        st.plotly_chart(sankey_figure(data), width="stretch")

# --- Category drill-down ----------------------------------------------------

with tab_drill:
    cats = category_totals(view)
    if cats.empty:
        st.info("No spending in this date range.")
    else:
        category = st.selectbox(
            "Category",
            list(cats.index),
            format_func=lambda c: f"{c}  ({money(cats[c])})",
        )
        d = category_detail(view, category)
        m1, m2, m3 = st.columns(3)
        m1.metric("Total spent", money(d.total))
        m2.metric("Transactions", f"{d.count:,}")
        m3.metric("Average", money(d.average))

        if not d.top_merchants.empty:
            top = d.top_merchants.rename_axis("Merchant").reset_index(name="Spent")
            fig = px.bar(top, x="Spent", y="Merchant", orientation="h", text_auto="$,.0f")
            fig.update_layout(
                title=f"Top {len(top)} merchants",
                yaxis=dict(autorange="reversed", title=None),
                xaxis=dict(title=None, tickprefix="$"),
                height=80 + 34 * len(top),
                margin=dict(l=10, r=10, t=40, b=10),
            )
            fig.update_traces(marker_color="#8a7fb8")
            st.plotly_chart(fig, width="stretch")

        table = d.transactions[["date", "name", "amount", "account"]].copy()
        table["date"] = table["date"].dt.date
        st.dataframe(
            table,
            hide_index=True,
            width="stretch",
            column_config={
                "date": st.column_config.DateColumn("Date"),
                "name": "Merchant",
                "amount": st.column_config.NumberColumn("Amount", format="dollar"),
                "account": "Account",
            },
        )
