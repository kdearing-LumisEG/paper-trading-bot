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

The strategy runtime supports durable Alpaca paper execution. Live trading is
not supported. Execution remains a dry run unless `--execute` is supplied, and
the active Alpaca client must positively prove both sandbox mode and the paper
endpoint before an order can be submitted or canceled.

Real paper submission is available only through the strategy-controlled paths:

```powershell
.\.venv\Scripts\python.exe -m trading_bot.main run-once --execute
.\.venv\Scripts\python.exe -m trading_bot.main signal --signal enter_long --signal-time 2026-01-02T15:00:00Z --reference-price 500 --execute
```

Do not add `--execute` when validating configuration or broker state. Manual
`buy` and `sell` commands remain available for dry-run inspection, but their
`--execute` forms are intentionally blocked.

## Execution recovery

Strategy actions are persisted to `logs/execution/order_state.json` before the
broker call. A deterministic intent and Alpaca client-order ID prevent the same
logical action from being submitted twice after a retry or restart. Confirmed
partial fills immediately update the owned position quantity. When submission
or cancellation cannot be proven, the intent becomes
`reconciliation_required`; it is never automatically replaced or resubmitted.

Run these read-only checks before a controlled paper session:

```powershell
.\.venv\Scripts\python.exe -m trading_bot.main reconcile
.\.venv\Scripts\python.exe -m trading_bot.main positions
.\.venv\Scripts\python.exe -m trading_bot.main lock-status
```

Reconciliation matches broker orders by deterministic client-order ID and
fails closed for unknown orders, unresolved intents, quantity mismatches, and
open legacy position records without a position-generation ID. Version-1 flat
position records remain readable; open legacy records are not adopted or
upgraded automatically. The runtime lock is never cleared automatically.

Lifecycle audit events are appended to
`logs/execution/order_lifecycle.jsonl`. Configuration for order state and
cancellation confirmation lives under `paper_execution` in
`config/strategy.yaml`.

## Autonomous paper session

Start the bot manually during the regular session or up to the configured
same-day pre-open window before it:

```powershell
# Safe validation; never submits an order
.\.venv\Scripts\python.exe -m trading_bot.main run-session

# Alpaca paper orders only; never live trading
.\.venv\Scripts\python.exe -m trading_bot.main run-session --execute
```

The command acquires `logs/execution/runtime.lock` before startup
reconciliation and holds it while waiting, polling, recovering, flattening,
and writing the final report. Do not run another mutating command or manually
change the Alpaca account while it is active. Read-only account inspection is
permitted, but its output is only observational.

The bot evaluates completed bars, suppresses duplicate bars, blocks new entry
inside the configured pre-close flatten window, and uses the durable execution
core for strategy, `session_flatten`, `emergency_flatten`, and
`operator_shutdown_flatten` actions. A transient read error enters bounded
recovery. Unknown orders, unresolved intents, generation/quantity mismatches,
or persistence uncertainty fail closed and produce an urgent-review report;
they never cause an ambiguous order retry.

Use one `Ctrl+C` and wait for graceful cleanup. A safely owned open paper
position is flattened only after all certainty checks pass. Power loss or a
forced process kill is recovered later through the existing lock and
reconciliation procedure; the lock is never cleared automatically.

Current status is written atomically to
`logs/execution/latest_session_status.json`. Historical JSON and Markdown
reports, latest report copies, and clearly named urgent-review reports are in
`logs/reports/`; session events append to
`logs/execution/session_events.jsonl`. The process exits automatically after
the session. If a report requires review, run `lock-status`, `positions`, and
`reconcile` before considering another session.

External alerts, stop-loss, and take-profit are not implemented. Live trading
is not supported.

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
