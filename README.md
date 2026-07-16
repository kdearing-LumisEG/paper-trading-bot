# Paper-Trading Bot

An educational Python project for learning:

- Market-data APIs
- Data validation
- Backtesting
- Risk management
- Paper-trading execution
- Automated testing
- AI-assisted software development

## Current milestone

Milestone 2D: Equity curve generation, performance reporting, and export utilities.

No live trading is permitted during the current stage.

## Example usage

```python
from pathlib import Path

import pandas as pd

from trading_bot import load_bars
from trading_bot.reporting import export_backtest_report, PerformanceMetrics
from trading_bot.strategies.indicators import add_ema_indicators
from trading_bot.strategies.signals import add_crossover_signals
from trading_bot.backtest import run_backtest

bars = load_bars(Path("data/processed/SPY_15min.parquet"))

bars_with_ema = add_ema_indicators(
    bars,
    fast_period=9,
    slow_period=21,
)

bars_with_signals = add_crossover_signals(bars_with_ema)

backtest_result = run_backtest(
    bars_with_signals[["timestamp", "open", "close", "signal"]],
    starting_cash=10_000.0,
)

metrics = PerformanceMetrics.from_backtest_result(backtest_result)

paths = export_backtest_report(
    trades=backtest_result.to_frame(),
    equity_curve=backtest_result.equity_curve,
    summary=metrics.to_dict(),
    experiment_name="spy_15min_ema_9_21_baseline",
)

print(paths)
```

Experiment outputs are saved under `logs/backtests/<experiment_name>/`, for example:

- `logs/backtests/spy_15min_ema_9_21_baseline/trade_log.csv`
- `logs/backtests/spy_15min_ema_9_21_baseline/equity_curve.csv`
- `logs/backtests/spy_15min_ema_9_21_baseline/performance_summary.json`
