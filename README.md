# FlowLens

A local-only cash-flow visualizer. Load a transaction CSV and see where your money goes:

- **Sankey diagram**: income flowing into savings and each spending category, labeled with % of income.
- **Metrics header**: income, expenses, savings and savings rate for the selected date range.
- **Date range**: presets (Last Week to All Time) or a custom start/end date.
- **Category drill-down**: top 10 merchants, totals and the full transaction list for any category.
- **Projections**: projected annual spend per category, and per-category targets (% of income)
  marked **On pace** or **Over**. Targets are saved locally and survive a restart.

Your data never leaves your machine. The CSV is held in memory by the local Streamlit
process, the server binds to `localhost` only, and Streamlit usage stats are turned off
(`.streamlit/config.toml`).

## Run it locally

Requires [uv](https://docs.astral.sh/uv/) (it installs the pinned Python 3.13 and dependencies for you).

```bash
git clone https://github.com/li-brandon/FlowLens.git
cd FlowLens
uv sync
uv run streamlit run app.py
```

Then open <http://localhost:8501>. Upload your own export, or tick **Use sample data** in
the sidebar to explore `samples/sample_transactions.csv` (fake data only).

Run the tests:

```bash
uv run pytest
```

## CSV format

FlowLens reads the [Copilot Money](https://copilot.money) export format. Required columns:

| Column | Meaning |
|---|---|
| `date` | Transaction date (`YYYY-MM-DD` or any format pandas can parse) |
| `name` | Merchant / description |
| `amount` | Positive = money out, negative = money in (refunds, income) |
| `type` | `regular`, `income` or `internal transfer` |
| `category` | Spending category (blank becomes **Other**, so no spending is hidden) |
| `account` | Account name |
| `excluded` | `true` / `false` |

Extra columns (such as `tags`) are kept but not required. Rows with an unreadable date or
amount are listed in a warning instead of being silently dropped.

### Calculation rules

- **Income**: rows with type `income`, counted as absolute values. Excluded income is still counted.
- **Expenses**: all other rows, except transfers and rows marked `excluded`. Refunds (negative amounts) reduce their category's total.
- **Transfers**: any type containing `transfer` is ignored for income and expenses.
- **Savings** = income - expenses. **Savings rate** = savings / income × 100 (shown as n/a when income is 0).

### Projection rules

- The selected date range is treated as typical. **Months in range** = inclusive days / 30.44.
- **Monthly average** = a category's net spend in range / months in range. **Projected annual** = monthly average × 12.
- **Annual income** is the range's income annualized the same way. Toggle **Override annual income** to enter your own.
- **Targets** are a percent of annual income. A category is **On pace** when its projected annual spend
  is at or below the target amount, otherwise **Over**. With no income, targets show **No income**.
- Targets are saved to `~/.flowlens/targets.json` (outside the repo). Set `FLOWLENS_TARGETS_PATH`
  to use another file. Targets for categories not in the current range are kept.

## Real data safety

`.gitignore` blocks every `*.csv` except files under `samples/` and `tests/fixtures/`, plus
`.env` files and Streamlit secrets. Don't put real exports in those folders.

## Credits

FlowLens is inspired by [CashFlow](https://github.com/KushalBKusram/CashFlow) by Kushal Kusram
(MIT License). FlowLens is an independent reimplementation: no code from CashFlow was copied.
If upstream code is ever copied in, its copyright line ("Copyright (c) 2026 Kushal Kusram") and
MIT permission notice must be added to a `NOTICE` file.

## License

MIT. See [LICENSE](LICENSE).
