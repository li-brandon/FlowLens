"""Build the income -> savings/categories Sankey diagram."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import plotly.graph_objects as go

from .calc import category_totals, total_income

INCOME_COLOR = "#2e7d5b"
SAVINGS_COLOR = "#3b82c4"
SHORTFALL_COLOR = "#d64545"
CATEGORY_COLOR = "#8a7fb8"


@dataclass
class SankeyData:
    labels: list[str] = field(default_factory=list)
    colors: list[str] = field(default_factory=list)
    sources: list[int] = field(default_factory=list)
    targets: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    overspent: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.values


def _money(x: float) -> str:
    return f"${x:,.0f}"


def _pct(x: float, income: float) -> str:
    return f"{x / income * 100:.1f}% of income" if income > 0 else "no income"


def build_sankey(df: pd.DataFrame) -> SankeyData:
    """Compute nodes and links.

    Income flows into Savings and one node per spending category. When spending
    exceeds income, an "Overspent" node supplies the gap so the chart still balances.
    Categories whose refunds exceed spending (net <= 0) are left out of the diagram.
    """
    income = total_income(df)
    cats = category_totals(df)
    cats = cats[cats > 0]
    spent = float(cats.sum())
    data = SankeyData()
    if income <= 0 and spent <= 0:
        return data

    shortfall = max(0.0, spent - income)
    savings = max(0.0, income - spent)
    data.overspent = shortfall

    def node(label: str, color: str) -> int:
        data.labels.append(label)
        data.colors.append(color)
        return len(data.labels) - 1

    def link(src: int, dst: int, value: float) -> None:
        if value > 0:
            data.sources.append(src)
            data.targets.append(dst)
            data.values.append(value)

    income_node = node(f"Income {_money(income)}", INCOME_COLOR) if income > 0 else None
    short_node = (
        node(f"Overspent {_money(shortfall)} ({_pct(shortfall, income)})", SHORTFALL_COLOR)
        if shortfall > 0
        else None
    )

    # Share of each category funded by income vs. by the shortfall.
    funded = min(income, spent) / spent if spent > 0 else 0.0
    for name, amount in cats.items():
        idx = node(f"{name} {_money(amount)} ({_pct(amount, income)})", CATEGORY_COLOR)
        if income_node is not None:
            link(income_node, idx, amount * funded)
        if short_node is not None:
            link(short_node, idx, amount * (1 - funded))

    if savings > 0 and income_node is not None:
        idx = node(f"Savings {_money(savings)} ({_pct(savings, income)})", SAVINGS_COLOR)
        link(income_node, idx, savings)

    return data


def sankey_figure(data: SankeyData) -> go.Figure:
    fig = go.Figure(
        go.Sankey(
            arrangement="snap",
            valueformat="$,.2f",
            node=dict(label=data.labels, color=data.colors, pad=18, thickness=18),
            link=dict(
                source=data.sources,
                target=data.targets,
                value=data.values,
                color=[_fade(data.colors[s]) for s in data.sources],
            ),
        )
    )
    fig.update_layout(
        height=max(420, 34 * len(data.labels)),
        margin=dict(l=10, r=10, t=10, b=10),
        font=dict(size=13),
    )
    return fig


def _fade(hex_color: str, alpha: float = 0.35) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"
