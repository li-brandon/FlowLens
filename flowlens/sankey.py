"""Build the income -> spending Sankey diagram in three views.

- Category: income sources -> Income -> each spending category (+ Savings)
- Group:    Income -> each category group (+ Savings)
- Both:     income sources -> Income -> groups -> categories (+ Savings)

When spending exceeds income, an "Overspent" node supplies the gap so the chart
still balances. Categories whose refunds exceed spending (net <= 0) are left out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import plotly.graph_objects as go

from .calc import category_totals, expense_rows, income_rows, total_income

CATEGORY, GROUP, BOTH = "Category", "Group", "Both"
VIEWS: tuple[str, ...] = (CATEGORY, GROUP, BOTH)

# Categorical slots validated (dataviz validate_palette.js) in both modes. Green and
# red are left out so categories never look like Savings or Overspent. Every node
# carries a text label, which is the relief for the light-mode contrast warning.
PALETTE_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#6250d6")
PALETTE_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#9085e9")
INCOME_COLOR = "#6b7c8f"
SAVINGS_COLOR = "#008300"
SHORTFALL_COLOR = "#e34948"


@dataclass
class SankeyData:
    names: list[str] = field(default_factory=list)  # plain node names
    labels: list[str] = field(default_factory=list)  # display labels (HTML)
    colors: list[str] = field(default_factory=list)
    columns: list[list[tuple[int, float]]] = field(default_factory=list)  # (node, value), top to bottom
    sources: list[int] = field(default_factory=list)
    targets: list[int] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    overspent: float = 0.0

    @property
    def is_empty(self) -> bool:
        return not self.values


def has_groups(df: pd.DataFrame) -> bool:
    return "group" in df.columns and bool(df["group"].ne("").any())


def color_keys(df: pd.DataFrame) -> list[str]:
    """Stable order of the entities that get palette colors (groups if known).

    Build it from the full dataset, not the filtered view, so changing the date
    range never repaints a group or category.
    """
    col = "group" if has_groups(df) else "category"
    return sorted(expense_rows(df)[col].unique())


def _money(x: float) -> str:
    return f"${x:,.2f}"


def build_sankey(
    df: pd.DataFrame,
    view: str = CATEGORY,
    keys: list[str] | None = None,
    dark: bool = False,
    show_income: bool = True,
    show_overspent: bool = True,
) -> SankeyData:
    """Nodes and links for ``view``.

    ``show_income=False`` replaces income sources, Income, Overspent and Savings with
    one "Spending" node, leaving only where the money went. ``show_overspent=False``
    drops the Overspent node and lets Income feed every category in full.
    ``data.overspent`` always reports the real gap so the app can still mention it.
    """
    if view not in VIEWS:
        raise ValueError(f"Unknown view: {view}")
    grouped = has_groups(df)
    if not grouped:
        view = CATEGORY

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

    group_of = (
        expense_rows(df).groupby("category")["group"].first() if grouped else pd.Series(dtype=str)
    )
    palette = PALETTE_DARK if dark else PALETTE_LIGHT
    keys = keys if keys is not None else color_keys(df)

    def color_for(category: str | None = None, group: str | None = None) -> str:
        key = group if group is not None else (group_of.get(category, category) if grouped else category)
        idx = keys.index(key) if key in keys else len(keys)
        return palette[idx % len(palette)]

    def label(name: str, value: float) -> str:
        pct = f" ({value / income * 100:.1f}%)" if income > 0 else ""
        return f"{name}<br><b>{_money(value)}{pct}</b>"

    columns = data.columns

    def node(name: str, value: float, color: str, column: int) -> int:
        data.names.append(name)
        data.labels.append(label(name, value))
        data.colors.append(color)
        while len(columns) <= column:
            columns.append([])
        columns[column].append((len(data.names) - 1, value))
        return len(data.names) - 1

    def link(src: int, dst: int, value: float) -> None:
        if value > 0:
            data.sources.append(src)
            data.targets.append(dst)
            data.values.append(value)

    # Without income (hidden, or none while Overspent is hidden) the chart starts
    # from total spending instead.
    if not show_income or (income <= 0 and not show_overspent):
        if spent <= 0:
            return SankeyData()
        root = node("Spending", spent, INCOME_COLOR, 0)
        _spending_layers(view, cats, group_of, lambda idx, v: link(root, idx, v), 1, node, link, color_for)
        return data

    col = 0
    by_source = (
        income_rows(df).groupby("category")["amount"].apply(lambda s: s.abs().sum())
    )
    by_source = by_source[by_source > 0].sort_values(ascending=False)
    # A single source would just repeat the Income node, so it's only shown when
    # income comes from two or more categories.
    income_sources = view in (CATEGORY, BOTH) and len(by_source) > 1
    if income_sources:
        source_nodes = [(node(n, float(v), INCOME_COLOR, 0), float(v)) for n, v in by_source.items()]
        col = 1

    income_node = node("Income", income, INCOME_COLOR, col) if income > 0 else None
    short_node = (
        node("Overspent", shortfall, SHORTFALL_COLOR, col) if shortfall > 0 and show_overspent else None
    )
    if income_sources:
        for idx, v in source_nodes:
            link(idx, income_node, v)
    col += 1

    # Share of each first-layer node funded by income vs. by the shortfall.
    funded = min(income, spent) / spent if spent > 0 and short_node is not None else 1.0

    def fund(idx: int, amount: float) -> None:
        if income_node is not None:
            link(income_node, idx, amount * funded)
        if short_node is not None:
            link(short_node, idx, amount * (1 - funded))

    _spending_layers(view, cats, group_of, fund, col, node, link, color_for)

    if savings > 0 and income_node is not None:
        link(income_node, node("Savings", savings, SAVINGS_COLOR, col), savings)

    return data


def _spending_layers(view, cats, group_of, feed, col, node, link, color_for) -> None:
    """Add the group and/or category columns. ``feed(node, amount)`` links in the
    money that supplies each first-layer node."""
    if view == CATEGORY:
        for name, amount in cats.items():
            feed(node(name, float(amount), color_for(category=name), col), float(amount))
        return
    cat_group = group_of.reindex(cats.index).fillna(cats.index.to_series())
    groups = cats.groupby(cat_group).sum().sort_values(ascending=False)
    group_nodes = {}
    for g, amount in groups.items():
        group_nodes[g] = node(g, float(amount), color_for(group=g), col)
        feed(group_nodes[g], float(amount))
    if view == BOTH:
        for g in groups.index:
            members = cats[cat_group == g]
            for name, amount in members.sort_values(ascending=False).items():
                link(group_nodes[g], node(name, float(amount), color_for(group=g), col + 1), float(amount))


# Gap between nodes in a column, in pixels. Big enough for a two-line label, so
# small categories never print on top of each other.
NODE_GAP_PX = 44
MARGIN_PX = 10


def figure_height(data: SankeyData) -> int:
    tallest = max((len(c) for c in data.columns), default=1)
    return max(520, (NODE_GAP_PX + 16) * tallest + 2 * MARGIN_PX)


def node_positions(data: SankeyData, height: int) -> tuple[list[float], list[float]]:
    """Node centers in [0, 1]: columns left to right, nodes in insertion order top down.

    Plotly would otherwise reorder nodes to reduce crossings, which scatters the
    biggest categories. Plotly sizes a node as value * ky, with
    ky = (plot height - gaps) / column total for the fullest column; using the same
    gap here keeps our centers lined up with its bars.
    """
    plot_h = height - 2 * MARGIN_PX
    pad = NODE_GAP_PX / plot_h
    x = [0.0] * len(data.names)
    y = [0.0] * len(data.names)
    cols = [c for c in data.columns if c]
    scale = min((1 - pad * (len(c) - 1)) / max(sum(v for _, v in c), 1e-9) for c in cols)
    n = len(cols)
    if n >= 4:
        # Labels sit right of a node, except in the last column where they sit left,
        # so the last gap holds two labels. Give it half the width.
        xs = [i * 0.5 / (n - 2) for i in range(n - 1)] + [1.0]
    else:
        xs = [i / (n - 1) if n > 1 else 0.5 for i in range(n)]
    for ci, column in enumerate(cols):
        cx = xs[ci]
        cursor = 0.0
        for idx, value in column:
            h = value * scale
            x[idx] = min(max(cx, 0.001), 0.999)
            y[idx] = min(max(cursor + h / 2, 0.001), 0.999)
            cursor += h + pad
    return x, y


def sankey_figure(data: SankeyData) -> go.Figure:
    height = figure_height(data)
    x, y = node_positions(data, height)
    fig = go.Figure(
        go.Sankey(
            arrangement="fixed",
            valueformat="$,.2f",
            node=dict(
                label=data.labels,
                color=data.colors,
                x=x,
                y=y,
                pad=NODE_GAP_PX,
                thickness=14,
                line=dict(width=0),
                hovertemplate="%{label}<extra></extra>",
            ),
            link=dict(
                source=data.sources,
                target=data.targets,
                value=data.values,
                color=[_fade(data.colors[t]) for t in data.targets],
                customdata=[
                    f"{data.names[s]} → {data.names[t]}: {_money(v)}"
                    for s, t, v in zip(data.sources, data.targets, data.values)
                ],
                hovertemplate="%{customdata}<extra></extra>",
            ),
        )
    )
    fig.update_layout(
        height=height,
        margin=dict(l=MARGIN_PX, r=MARGIN_PX, t=MARGIN_PX, b=MARGIN_PX),
        font=dict(size=13),
    )
    return fig


def _fade(hex_color: str, alpha: float = 0.3) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"
