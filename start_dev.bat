@echo off
echo ===================================================
echo     AI Trade Manager Development Server
echo ===================================================
echo.
echo [1] Starting Docker containers...
docker-compose -f docker-compose-dev.yml up -d db opensearch opensearch-dashboards

echo.
echo [2] Starting Backend Server in new window...
start "AI Trade Manager - Backend" cmd /k "venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo.
echo [3] Starting Frontend Server in new window...
start "AI Trade Manager - Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo All commands sent. Close this window if you want.
pause
