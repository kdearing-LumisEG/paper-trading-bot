# Technical Decisions

## D001: Begin with deterministic rules

The first strategy will use explicit, reproducible rules rather than AI-generated trading decisions.

## D002: Start with one instrument

The initial system will analyze SPY using 15-minute bars.

## D003: Separate system components

Market data, validation, strategy logic, risk management, execution, and reporting will remain separate modules.

## D004: Protect credentials

API credentials will be stored in a local `.env` file that is excluded from Git.
