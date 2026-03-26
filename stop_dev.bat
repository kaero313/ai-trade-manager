@echo off
echo ===================================================
echo     AI Trade Manager Stopper
echo ===================================================
echo.
echo Stopping Docker containers...
docker-compose -f docker-compose-dev.yml down

echo.
echo To fully stop the backend/frontend servers,
echo please close the black CMD windows manually.
pause
