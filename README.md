# Trading Bot (Upbit KRW Spot)

Local Python + FastAPI trading bot scaffolding for Upbit KRW spot markets.

## Quick start

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
```

Run the API:

```bash
uvicorn app.main:app --reload
```

Open:
- UI: http://127.0.0.1:8000/
- API docs: http://127.0.0.1:8000/docs

### Upbit test endpoints
Requires `.env` with `UPBIT_ACCESS_KEY` and `UPBIT_SECRET_KEY`.
- GET `/api/upbit/accounts`
- GET `/api/upbit/order?uuid=...` or `identifier=...`
- GET `/api/upbit/orders/open`
- GET `/api/upbit/orders/closed`

## Config
Copy `.env.example` to `.env` and fill in keys.
