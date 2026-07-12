# Python Coding Standards — MERI Quant/Trading Scripts

**Scope:** backtesting, live/automated trading (IBKR), and research/data-analysis scripts (TS, Astro Box, natal-chart-style analysis, etc.)
**Audience:** written for solo use today, but structured so a future MERI colleague could pick up any script cold.

---

## 1. Why these standards exist

Quant code fails differently from normal software. The bugs that hurt you aren't crashes — they're **silent**:

- A backtest that leaks future data into a signal (lookahead bias) and looks amazing until you trade it live.
- A NaN that quietly propagates through a neural net and makes every prediction from that point on garbage — with no error thrown.
- A script that works today but can't be re-run in six months because you don't remember which data snapshot, which random seed, or which parameter set produced last month's "great" result.
- A live-order script with a typo in a ticker or quantity, executed with real IBKR capital, with no safety check to catch it.

These standards exist to make those four failure modes hard to trigger by accident. Everything else (formatting, naming, imports) is secondary — important for readability, but not where the real risk lives.

---

## 2. Toolchain (2026 default stack)

Use this stack for every new script/project. It's fast, has one config file, and is what you'd want a future collaborator to already know.

| Purpose | Tool | Notes |
|---|---|---|
| Environments, dependencies, locking, running scripts | **uv** | Replaces pip/venv/pyenv/poetry. `uv init`, `uv add`, `uv run`. |
| Linting + formatting | **Ruff** | Replaces black/isort/flake8. Runs in milliseconds; auto-fix on save. |
| Type checking | **mypy** (stable) or **ty** (newer, from Astral — same team as uv/Ruff) | Use mypy if you want the mature plugin ecosystem; try ty once it's stable in your editor. |
| Dataframes | **pandas** (what you already use) or **Polars** if a script becomes a performance bottleneck | Don't migrate existing scripts just for style points — only when speed actually matters. |

**Minimal `pyproject.toml` to start every project from:**

```toml
[project]
name = "meri-strategy-name"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest", "ruff", "mypy"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "N", "ANN", "S"]
# E/F = pycodestyle/pyflakes core, I = import sort, UP = modern syntax,
# B = bug-prone patterns, N = naming, ANN = require type hints, S = security (bandit-style)

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.12"
disallow_untyped_defs = true
warn_return_any = true
```

Commands you'll actually run day to day:
```bash
uv add pandas numpy    # add a dependency
uv run python script.py
ruff check . --fix     # lint + autofix
ruff format .          # format
mypy .                 # type check
```

---

## 3. The four pillars

### Pillar 1 — Reproducibility
A backtest result you can't reproduce isn't a result — it's an anecdote.

- **Pin your environment.** Commit `uv.lock`. Never "just pip install" ad hoc into a script you'll rely on later.
- **Pin your data.** Save (or clearly log) the exact data snapshot/date-range used for any backtest that produces a number you'll act on. If you pull from IBKR or a data vendor, save the raw pull to disk before transforming it.
- **Seed everything stochastic.** Neural nets, random splits, Monte Carlo — set and log the seed.
```python
import random
import numpy as np

SEED = 42
random.seed(SEED)
np.random.seed(SEED)
# log it
print(f"Run seed: {SEED}")
```
- **Log parameters, not just results.** Every backtest run should write out (to a file, not just stdout) the parameters that produced it: date range, tickers, NN topology, ZigZag sensitivity, etc. A results number with no config attached is worthless in three months.

### Pillar 2 — No lookahead / no silent leakage
This is the single most common way quant backtests lie to you.

- Never use a value in a feature/signal that wouldn't have been known at that point in time. This includes indicators computed with `.rolling()` windows that accidentally include the current (not-yet-closed) bar, or news/fundamental data joined by date without checking the actual release timestamp.
- When splitting train/test or doing Walk Forward Analysis, **always split by time**, never randomly, for any time-series model.
- Add an explicit assertion or comment at every point future data could leak in:
```python
# Explicit lookahead guard: signal at time t must only use data up to t-1
assert (features.index < prediction_date).all(), "Lookahead leak: features include future data"
```

### Pillar 3 — Fail loud, not silent
A silent NaN or a swallowed exception in a trading script is how you lose money without noticing.

- Never use a bare `except:`. Catch specific exceptions.
- After any operation that can produce NaN/Inf (division, log, neural net output), check for it explicitly rather than letting it flow downstream.
```python
# Bad — fails silently, NN trains on garbage
result = np.log(prices / prices.shift(1))

# Good — fails loud
returns = prices / prices.shift(1)
if (returns <= 0).any():
    raise ValueError("Non-positive price ratio detected — check for bad ticks or splits")
log_returns = np.log(returns)
```
- For anything touching **live order execution**, add a hard sanity check before the order fires — max position size, max order value, ticker sanity check. This is non-negotiable even for solo use; it's the difference between a typo and a costly mistake.
```python
MAX_ORDER_VALUE_USD = 5_000  # hard ceiling, adjust deliberately, never bypass silently

def place_order(ticker: str, qty: int, price: float) -> None:
    order_value = qty * price
    if order_value > MAX_ORDER_VALUE_USD:
        raise ValueError(
            f"Order value ${order_value:,.2f} exceeds safety ceiling "
            f"${MAX_ORDER_VALUE_USD:,.2f} — aborting. Adjust MAX_ORDER_VALUE_USD "
            f"deliberately if this is intentional."
        )
    # ... actual IBKR order call
```

### Pillar 4 — Readable in a year (by you, or by someone else)
Optimize for "can I trust this script's output without re-reading every line" — not for cleverness.

- **Type hints everywhere** — they're the cheapest form of documentation and let mypy catch real bugs.
- **Docstrings that state the finance assumption, not just the mechanics.** "Computes RSI" is useless; "Computes 14-day RSI using close price; assumes no gaps in trading calendar" is useful.
- **No magic numbers.** Every threshold, lookback window, or ceiling gets a named constant at the top of the file.
- **One script = one clear purpose.** Backtest, live execution, and research/exploration scripts should be separate files, not one script with commented-out sections for "the live version."

---

## 4. Naming & style specifics

Ruff enforces most mechanical style automatically. The judgment calls Ruff can't make for you:

| Category | Convention | Example |
|---|---|---|
| Files | `snake_case`, verb or domain first | `backtest_zigzag_nn.py`, `ibkr_live_orders.py` |
| Functions | `snake_case`, verb-first | `compute_rsi()`, `load_ibkr_snapshot()` |
| Constants | `UPPER_SNAKE_CASE`, defined at module top | `MAX_ORDER_VALUE_USD = 5_000` |
| Tickers/symbols | Always `str`, always uppercase, never inferred from user input without validation | `ticker: str = "CRNX"` |
| DataFrames | Suffix with what it represents, not just `df` | `prices_df`, `signals_df`, not `df1`, `df2` |
| Dates | Always `datetime` or `pd.Timestamp`, never bare strings past the point of parsing | parse once at the boundary, then pass typed objects |

---

## 5. Project structure template

```
strategy-name/
├── pyproject.toml
├── uv.lock
├── README.md              # what this strategy does, in 3-5 sentences
├── config/
│   └── params.yaml         # all tunable parameters, not hardcoded in scripts
├── data/
│   └── raw/                 # untouched pulls, timestamped, never edited
├── src/
│   ├── data_loader.py
│   ├── signals.py
│   ├── backtest.py
│   └── live_execution.py    # kept separate from backtest.py, always
├── tests/
│   └── test_signals.py      # at minimum: test lookahead guards and NaN handling
└── runs/
    └── 2026-07-09_run1/     # one folder per backtest run: params + results + seed
```

---

## 6. Pre-flight checklist (use before trusting any backtest / running any live script)

See the companion checklist artifact — designed to be pasted at the top of a script or run through manually before you act on a result.

---

## 7. What NOT to over-invest in (given solo use today)

To keep this practical rather than aspirational:

- Skip CI/CD pipelines, pre-commit hook servers, or elaborate PR templates — solo use doesn't need them yet. Revisit if/when MERI colleagues start committing code.
- Skip 100% test coverage goals. Prioritize tests for Pillar 2 and 3 issues (lookahead, NaN propagation, order-size guards) over trivial getter/setter tests.
- Don't chase `ANN` (type-hint) or `S` (security) Ruff rules to zero on day one for research/throwaway analysis scripts — apply the full rule set strictly to `live_execution.py` and `backtest.py`, be more relaxed on one-off exploration scripts.
