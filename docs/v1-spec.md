# Trading Bot v1 Spec (Upbit KRW, Spot)

## 1) Overview
Build a local Python + FastAPI trading bot for Upbit KRW spot markets. The bot runs 24/7, trades on 1h candles, and is controlled via a web UI and Telegram. It must provide real-time status, balance, PnL, and execution notifications.

## 2) Goals
- Automated trading on Upbit KRW spot markets
- User-configurable UI for symbols, allocation, strategy params, risk, schedule
- Telegram control and notifications
- Robust risk controls and logging
- Local execution with lightweight storage

## 3) Non-goals (v1)
- Futures/margin trading
- Complex portfolio optimization
- Fully featured backtesting suite
- Multi-exchange support

## 4) Core Constraints
- Exchange: Upbit
- Market: KRW only
- Timeframe: 1h candles
- Max capital allocation: 10% of account equity
- Daily loss limit: 5% (of allocated capital at start of day)
- Runtime: local machine, 24/7

## 5) Strategy (v1 default)
**Trend-following EMA cross with RSI filter**
- Indicators:
  - EMA fast = 12
  - EMA slow = 26
  - RSI = 14
- Entry (long only):
  - EMA fast crosses above EMA slow
  - RSI > 50
- Exit:
  - EMA fast crosses below EMA slow, OR
  - Trailing stop (configurable, default 3%)

All parameters are configurable in UI.

## 6) Order Policy
- Entry: limit orders (reduce slippage)
- Emergency exit: market-like order when needed
- Validate minimum order size and price tick per market
- Throttle requests to respect rate limits

## 7) Risk Management
- Total capital used by bot <= 10% of account equity
- Position sizing per trade: % of allocated capital (configurable, default 20%)
- Max concurrent positions: configurable (default 3)
- Daily loss limit: 5% of allocated capital at day start
- Cooldown after 2 consecutive losses (default 60 minutes)

## 8) Data & Storage
- Market data: WebSocket ticker + REST candles
- Private data: WebSocket myAsset/myOrder + REST for orders
- Storage: SQLite
  - tables: orders, fills, positions, balances, signals, settings, logs

## 9) Telegram Integration
- Receive commands:
  - /start, /stop, /status, /balance, /pnl, /positions, /setrisk
- Send notifications:
  - order placed/filled/canceled, daily PnL, errors

## 10) FastAPI UI & API
- UI pages (minimal):
  - Dashboard: bot status, balance, PnL
  - Settings: symbols, allocation, strategy params, risk, schedule
- API endpoints (initial):
  - GET /health
  - GET /status
  - GET /config
  - POST /config
  - POST /bot/start
  - POST /bot/stop
  - GET /positions
  - GET /orders

## 11) Scheduling
- Default: 24/7
- Optional trading window config (start/end hours)

## 12) Logging & Observability
- Structured logs to file
- Error alerts to Telegram
- Daily summary message

## 13) Safety Switches
- Dry-run (paper) mode toggle
- Manual kill switch in UI and Telegram
