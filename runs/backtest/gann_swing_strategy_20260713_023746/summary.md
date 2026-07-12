# Gann mechanical swing strategy backtest — 20260713_023746 (CORRECTED)

Entry: close breaks above last confirmed 2-bar swing-high pivot. Stop: last confirmed
swing-low pivot. Target: 10.0% within 5 trading days.

CORRECTION (2026-07-13): the first version of this summary excluded "missed" signals
(window elapsed with neither stop nor target hit) from the resolved denominator, which
inflated the apparent hit rate to 61.8% (42/68). Counting "missed" as a resolved loss —
the same convention backtest.py itself uses for the existing committee — gives the honest
number below.

- Total entry signals found: 321
- Resolved (hit, stopped, or missed): 321
- Hit rate: 13.1%

## Comparison

- Gann mechanical swing strategy: 13.1%
- Existing 4-group committee (runs/backtest/backtest_20260712_155959/summary.md): 42.8%
- Naive base rate (every analyzed snapshot, same file): 25.3%

## Conclusion

The Gann mechanical swing strategy (2-bar swing-high breakout / swing-low stop) performs
WORSE than both the existing committee and the naive base rate on this 400-ticker,
6-month sample. It should NOT be wired into committee_signals.py as a 4th/5th vote in its
current form. Most signals (253/321, ~79%) never reach either the stop or the 10% target
within 5 trading days — the entry rule alone, without a support/resistance-based
target-sizing step, produces too many sideways-drift non-outcomes to be useful standalone.

Per this project'''s committee_signals_updated.py-mistake lesson (never wire an unproven
method just to have a vote), this strategy stays OUT of the live committee. This file and
its backtest harness remain available to re-test a revised version later (e.g. a
narrower entry filter, ADX trend gate, or different target/stop sizing) without
rebuilding the harness.
