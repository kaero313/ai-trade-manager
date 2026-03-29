@echo off
echo ===================================================
echo     AI Trade Manager Stopper
echo ===================================================
echo.
echo Stopping Docker containers...
docker-compose -f docker-compose-dev.yml down

echo.
echo.
echo Stopping Backend and Frontend servers...
taskkill /fi "WINDOWTITLE eq AI Trade Manager - Backend*" /f /t >nul 2>&1
taskkill /fi "WINDOWTITLE eq AI Trade Manager - Frontend*" /f /t >nul 2>&1

echo.
echo Cleaning up ports 8000 and 5173...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 "') do taskkill /f /pid %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":5173 "') do taskkill /f /pid %%a >nul 2>&1

echo.
echo All development servers and containers have been fully stopped.
pause
