# Technical Decisions

## D001: Begin with deterministic rules

The first strategy will use explicit, reproducible rules rather than AI-generated trading decisions.

## D002: Start with one instrument

The initial system will analyze SPY using 15-minute bars.

## D003: Separate system components

Market data, validation, strategy logic, risk management, execution, and reporting will remain separate modules.

## D004: Protect credentials

API credentials will be stored in a local `.env` file that is excluded from Git.

## D005: Equity marked to market

Equity is calculated using the current bar closing price, so an open position is marked to market at each bar close.

## D006: Gross performance reporting

Performance metrics are gross of fees and slippage.

## D007: Baseline is reference only

The buy-and-hold baseline is a reference calculation that may hold overnight and is not an apples-to-apples comparison with the intraday strategy.

## D008: Autonomous sessions remain bounded and paper-only

A manually launched session may wait only for the same New York market date,
uses bounded read recovery, and exits after the regular session. Emergency
flattening is allowed only for a reconciled, generation-aware owned position
with no unknown or unresolved order state. Runtime submits after a completed
bar and flattens before close; backtests use next-open fills, modeled costs,
and their own final-session close policy.
