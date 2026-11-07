"""FlowLens: local-only cash-flow visualizer.

Run with:  uv run streamlit run app.py
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from flowlens.adjustments import ACCOUNT as ADJUSTMENT_ACCOUNT
from flowlens.adjustments import REPEATS, Adjustment, with_adjustments
from flowlens.calc import category_totals, summarize
from flowlens.dates import CUSTOM, PRESETS, filter_range, preset_range
from flowlens.drilldown import category_detail
from flowlens.loader import CsvFormatError, LoadResult, load_transactions
from flowlens.payslips import ACCOUNT as PAYSLIP_ACCOUNT
from flowlens.payslips import (
    Columns,
    PayslipError,
    apply_payslips,
    guess_columns,
    guess_employer,
    parse_payslips,
    read_table,
)
from flowlens.projections import OVER, project
from flowlens.sankey import CATEGORY, VIEWS, build_sankey, color_keys, has_groups, sankey_figure
from flowlens.settings import DEFAULT_PATH, load_settings, save_settings

SAMPLE_PATH = Path(__file__).parent / "samples" / "sample_transactions.csv"

st.set_page_config(page_title="FlowLens", page_icon="💸", layout="wide")

# st.metric cuts long values off with "…" at narrow widths. Scale the text with the
# window instead and never truncate.
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] { font-size: clamp(1.1rem, 2.4vw, 2.25rem); }
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] * {
        overflow: visible !important;
        text-overflow: clip !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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
    pay_upload = st.file_uploader(
        "Workday payslips (optional)",
        type=["xlsx", "csv"],
        help="Workday → Pay → Payslips → export to Excel. Net pay replaces the paycheck "
        "deposits in your CSV, so pay split into accounts Copilot can't see is counted.",
    )

is_sample = use_sample or upload is None
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

payslip_note = None
if pay_upload is not None and not is_sample:
    with st.sidebar:
        try:
            table = read_table(pay_upload.getvalue(), pay_upload.name)
        except PayslipError as exc:
            st.error(f"Couldn't read **{pay_upload.name}**: {exc}")
            table = None
        if table is not None:
            try:
                guess = guess_columns(table)
            except PayslipError as exc:
                st.warning(str(exc))
                guess = None
            names = list(table.columns)
            date_col = st.selectbox("Pay date column", names, index=names.index(guess.date) if guess else 0)
            net_col = st.selectbox("Net pay column", names, index=names.index(guess.net) if guess else 0)
            employer = st.text_input(
                "Paycheck deposits in the CSV contain",
                value=guess_employer(txns),
                help="Income rows with this text, inside the payslips' dates, are replaced "
                "by payslip net pay so nothing is counted twice.",
            )
            payslips = parse_payslips(table, Columns(date=date_col, net=net_col))
            if payslips.empty:
                st.warning("No payslips with a date and a net pay amount were found.")
            else:
                txns, replaced = apply_payslips(txns, payslips, employer)
                payslip_note = (
                    f"{len(payslips)} payslips ({payslips['date'].min():%b %d, %Y} → "
                    f"{payslips['date'].max():%b %d, %Y}), net pay {money(payslips['net'].sum())}. "
                    f"Replaced {replaced} paycheck deposit(s) from the CSV."
                )
                st.caption(payslip_note)

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

settings = load_settings()
if settings.warning:
    st.warning(settings.warning)
# Manual income adjustments only apply to your own data, never the fake sample.
adjustments = [] if is_sample else settings.adjustments
view = filter_range(with_adjustments(txns, adjustments), start, end)
is_adjustment = view["account"].eq(ADJUSTMENT_ACCOUNT) | view["account"].eq(PAYSLIP_ACCOUNT)

# --- Header metrics ---------------------------------------------------------

st.title("Cash flow")
adjusted = float(-view.loc[is_adjustment, "amount"].sum())
st.caption(
    f"{source_name} · {int((~is_adjustment).sum()):,} transactions in range"
    + (" · paychecks from **Workday payslips**" if payslip_note else "")
    + (f" · includes **{money(adjusted)}** of payslip pay and manual adjustments" if adjusted else "")
)
if payslip_note and adjustments:
    st.caption(
        "⚠️ You have payslips and manual income adjustments. Remove adjustments for "
        "paychecks the payslips now cover, or that pay is counted twice."
    )

s = summarize(view)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Income", money(s.income))
c2.metric("Expenses", money(s.expenses))
c3.metric("Savings", money(s.savings))
c4.metric("Savings rate", "n/a" if s.savings_rate is None else f"{s.savings_rate:.1f}%")

tab_flow, tab_drill, tab_proj, tab_adj = st.tabs(
    ["Flow", "Category drill-down", "Projections", "Income adjustments"]
)

# --- Sankey -----------------------------------------------------------------

with tab_flow:
    grouped = has_groups(txns)
    c_view, c_income, c_over = st.columns([2, 1, 1], vertical_alignment="center")
    sankey_view = c_view.segmented_control(
        "View", VIEWS, default=CATEGORY, key="sankey_view", label_visibility="collapsed",
        disabled=not grouped,
    ) or CATEGORY
    show_income = c_income.toggle("Income", value=True, key="sankey_income")
    show_overspent = c_over.toggle(
        "Overspent", value=True, key="sankey_overspent", disabled=not show_income,
        help="Hidden automatically when Income is off.",
    )
    if not grouped:
        st.caption(
            "Group and Both need a **parent category** (or **group**) column in the CSV. "
            "This file doesn't have one."
        )
    data = build_sankey(
        view,
        sankey_view,
        keys=color_keys(txns),
        dark=st.context.theme.type == "dark",
        show_income=show_income,
        show_overspent=show_overspent,
    )
    if data.is_empty:
        st.info("No income or spending in this date range.")
    else:
        if data.overspent > 0:
            shown = show_income and show_overspent
            st.warning(
                f"Spending exceeded income by **{money(data.overspent)}** in this range."
                + (" The red **Overspent** node shows the gap." if shown else "")
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

# --- Year-end projections ---------------------------------------------------

with tab_proj:
    auto = project(view, start, end)
    override = st.number_input(
        "Annual income override ($, 0 = auto-detect)",
        min_value=0.0,
        value=float(settings.income_override or 0.0),
        step=1000.0,
        help=f"Auto-detected from this range: {money(auto.detected_income)} per year.",
    )
    new_override = override or None
    if new_override != settings.income_override:
        settings.income_override = new_override
        save_settings(settings)

    p = project(view, start, end, targets=settings.targets, income_override=new_override)
    st.caption(
        f"Projected from {p.months:.1f} months of data ({start:%b %d, %Y} → {end:%b %d, %Y}). "
        f"Annual income: **{money(p.annual_income)}**"
        + (" (override)" if new_override else " (auto-detected)")
        + ". Targets are saved on this computer and stay after restarting."
    )
    if p.months < 1:
        st.info("Less than a month of data: projections will be rough.")

    if p.table.empty:
        st.info("No spending in this date range.")
    else:
        over = int((p.table["status"] == OVER).sum())
        if over:
            st.warning(f"{over} categor{'y is' if over == 1 else 'ies are'} over target.")
        cats_key = "|".join(p.table["category"])
        edited = st.data_editor(
            p.table.drop(columns=["target_amount"]),
            key=f"targets-{cats_key}",
            hide_index=True,
            width="stretch",
            disabled=["category", "spent", "monthly", "projected", "pct_of_income", "status"],
            column_config={
                "category": "Category",
                "spent": st.column_config.NumberColumn("Spent in range", format="dollar"),
                "monthly": st.column_config.NumberColumn("Monthly avg", format="dollar"),
                "projected": st.column_config.NumberColumn("Projected / year", format="dollar"),
                "pct_of_income": st.column_config.NumberColumn("% of income", format="%.1f%%"),
                "target_pct": st.column_config.NumberColumn(
                    "Target % of income", min_value=0.0, max_value=100.0, step=0.5, format="%.1f%%",
                    help="Leave blank for no target.",
                ),
                "status": "Status",
            },
        )
        # Categories outside this range keep their saved targets.
        new_targets = dict(settings.targets)
        for name, pct in zip(edited["category"], edited["target_pct"]):
            if pd.isna(pct):
                new_targets.pop(name, None)
            else:
                new_targets[name] = float(pct)
        if new_targets != settings.targets:
            settings.targets = new_targets
            save_settings(settings)
            st.rerun()  # redraw so status reflects the new targets
        st.caption(f"Saved in `{DEFAULT_PATH}`.")

# --- Income adjustments -----------------------------------------------------

with tab_adj:
    st.markdown(
        "Add income that isn't in your CSV: paychecks split into brokerage or crypto "
        "accounts (Copilot doesn't record their transactions), or an account that was "
        "disconnected. Adjustments count as income everywhere: the metrics, the Sankey "
        "(as their own income sources) and projections."
    )
    if is_sample:
        st.info("Adjustments aren't applied to the sample data. Upload your own CSV to use them.")
    current = pd.DataFrame(
        [a.to_dict() for a in settings.adjustments],
        columns=["name", "amount", "repeats", "start", "end"],
    )
    current["start"] = pd.to_datetime(current["start"]).dt.date
    current["end"] = pd.to_datetime(current["end"]).dt.date
    edited = st.data_editor(
        current,
        # A new key after each save drops the editor's pending edits, which are now
        # part of the saved rows (otherwise an added row would show up twice).
        key=f"adjustments-{st.session_state.get('adjustments_saves', 0)}",
        num_rows="dynamic",
        hide_index=True,
        width="stretch",
        column_config={
            "name": st.column_config.TextColumn("Name", help="Shown as an income source, e.g. Big Mac direct deposit"),
            "amount": st.column_config.NumberColumn("Amount", min_value=0.01, format="dollar"),
            "repeats": st.column_config.SelectboxColumn("Repeats", options=list(REPEATS), default=REPEATS[0]),
            "start": st.column_config.DateColumn("Date / first payday"),
            "end": st.column_config.DateColumn("Last payday", help="Leave blank to keep repeating"),
        },
    )
    rows = [Adjustment.from_dict(r) for r in edited.to_dict("records")]
    new = [a for a in rows if a]
    if new != settings.adjustments:
        settings.adjustments = new
        save_settings(settings)
        st.session_state["adjustments_saves"] = st.session_state.get("adjustments_saves", 0) + 1
        st.rerun()
    if len(new) < len(edited):
        st.caption("Rows need a name, an amount and a date before they're saved.")
    st.caption(
        "Recurring adjustments repeat up to your latest transaction. "
        f"Saved in `{DEFAULT_PATH}`, never in the repo."
    )
