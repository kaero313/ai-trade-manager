- GET `/api/upbit/orders/closed`

### Slack test endpoint
Requires `.env` with `SLACK_WEBHOOK_URL` (or pass `webhook_url` in body).
- POST `/api/slack/test`

### Slack Socket Mode (local)
Requires `.env` with `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`.
- DM or mention the bot with `잔고`, `balance`, `status`, `help`

## Config
Copy `.env.example` to `.env` and fill in keys.
