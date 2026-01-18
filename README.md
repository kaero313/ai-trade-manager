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

## Config
Copy `.env.example` to `.env` and fill in keys.
