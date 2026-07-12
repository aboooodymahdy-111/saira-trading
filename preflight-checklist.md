# Pre-Flight Checklist — Before Trusting a Backtest / Running a Live Script

Copy this into the top of a script as a comment, or run through it manually. Two sections: one for research/backtests, one for anything that touches real IBKR execution.

## A. Before trusting ANY backtest result

- [ ] Environment is pinned (`uv.lock` committed, no ad hoc installs since last run)
- [ ] Data snapshot used is saved to disk or timestamped/logged — not just "whatever the API returned today"
- [ ] Random seed is set and logged for any stochastic step (NN init, train/test split, Monte Carlo)
- [ ] Train/test split is time-based, not random, for any time-series model
- [ ] No feature uses data that wouldn't have been known at prediction time (explicit lookahead check passed)
- [ ] All parameters used for this run (NN topology, ZigZag sensitivity, lookback windows, tickers, date range) are logged alongside the result — not just visible in git history
- [ ] NaN/Inf checked explicitly after any division, log, or NN output step — not silently propagated
- [ ] Result is reproducible: re-running the script with the same config produces the same output

## B. Before running ANY script that places a live IBKR order

Everything in section A, plus:

- [ ] Hard ceiling on order value/position size is present in code and was NOT bypassed or commented out for this run
- [ ] Ticker symbol is validated (exists, matches expected exchange) before order submission
- [ ] Script has been dry-run (paper trading / simulated) at least once this session before going live
- [ ] You've manually re-read the exact order parameters (ticker, quantity, side, order type) immediately before execution — not just trusted what the script computed
- [ ] There's a way to see the fill/confirmation and it's been checked after execution, not assumed

## C. Before calling a research script "done" / archiving results

- [ ] Results folder includes: params used, seed, data snapshot reference, and the output — all together, not scattered
- [ ] A one-line note on what this run was testing and what you concluded (future-you will not remember)
- [ ] If accuracy was poor (as has happened with TS Neural Network runs), the note says *why*, if known — bad feature, insufficient data, overfitting, etc. — not just "didn't work"

