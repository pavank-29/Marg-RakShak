@echo off
title MARG-RAKSHAK Database Inspector
cd /d "%~dp0"
echo ========================================================
echo   MARG-RAKSHAK SQLite Database Records Inspection
echo ========================================================
echo.
py check_db.py %*
echo.
pause
