@echo off
title MargRakshak AI - Backend API (Port 8000)
cd /d "%~dp0BackEnd"
echo ========================================================
echo   Starting MargRakshak Backend API Server on Port 8000
echo ========================================================
echo.
py -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Trying fallback with python command...
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
)
pause
