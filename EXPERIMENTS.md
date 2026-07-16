# Experiment Log

## SPY 15-minute EMA 9/21 baseline

- Instrument: SPY
- Timeframe: 15-minute bars
- Data feed: `data/processed/SPY_15min.parquet`
- Date range: 2026-07-01 13:30:00+00:00 through 2026-07-14 19:45:00+00:00
- Strategy: EMA crossover signals (fast=9, slow=21)
- Trade execution: next bar open, long-only, one-share sizing
- Starting capital: $10,000
- Fees and slippage: none
- Overnight position behavior: strategy is allowed to hold positions across bars, but not explicitly overnight-managed in this simple test
- Resulting trades: 5
- Gross P&L: -$3.07
- Total return: -0.0307%
- Maximum drawdown: 6.2592%
- Exposure: 26.4957%
- Baseline buy-and-hold gross P&L: $6.975
- Baseline buy-and-hold return: 0.06975%

### Notes

- Baseline is a reference only and represents a one-share buy-and-hold position entered at the first bar open and exited at the final bar close.
- Experiment output files are exported to `logs/backtests/spy_15min_ema_9_21_baseline/`.

## Frozen EMA 9/21 Period Evaluation

**Protocol frozen:** 2026-07-16

### Strategy

- Symbol: SPY
- Bar interval: 15 minutes
- Fast EMA: 9
- Slow EMA: 21
- Position size: 1 share
- Direction: long only
- Entry execution: next bar open
- Exit execution: next bar open
- Overnight positions: not allowed
- Starting cash: $10,000
- Costs and slippage: not included in this Phase 2 experiment

### Research periods

- Development: 2024-01-01 through 2025-06-30
- Unseen evaluation: 2025-07-01 through 2026-06-30

### Data handling

- Indicators are calculated independently inside each period.
- The evaluation period does not inherit EMA state from development data.
- Incomplete source sessions are excluded in full and documented.
- Parameters will not be changed after viewing evaluation results.
- Once executed, the unseen evaluation period becomes seen data.

### Purpose

Evaluate whether the unchanged deterministic EMA crossover strategy behaves consistently outside the development period. This experiment is not evidence of live profitability because transaction costs, slippage, latency, and operational failures are not yet modeled.

### Results

#### Development period

- Bars: 9,636
- Trades: 188
- Gross P&L: $17.67
- Total return: 0.1767%
- Maximum drawdown: 0.2858%
- Win rate: 49.47%
- Profit factor: 1.1002
- Exposure: 23.38%

#### Unseen evaluation period

- Bars: 6,490
- Trades: 124
- Gross P&L: -$19.58
- Total return: -0.1958%
- Maximum drawdown: 0.4313%
- Win rate: 41.94%
- Profit factor: 0.8456
- Exposure: 21.23%

### Interpretation

The strategy produced only a marginal positive result during development and failed during the unseen evaluation period. Because transaction costs and slippage were excluded, the reported performance likely overstates realistic results.

The frozen 9/21 EMA strategy will be retained as a deterministic software and testing baseline, but it is not currently considered a viable paper-trading candidate.

The unseen evaluation period is now classified as seen data and will not be reused as an untouched holdout period.
