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
