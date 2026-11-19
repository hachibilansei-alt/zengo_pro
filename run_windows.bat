@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Zengo Pro - Start

echo ==========================================
echo             ZENGO PRO
echo ==========================================
echo.

where py >nul 2>nul
if not errorlevel 1 (
    echo [1/2] Checking and installing requirements...
    py -3 -m pip install -r requirements.txt
    if errorlevel 1 goto install_error
    echo.
    echo [2/2] Starting Zengo...
    py -3 app.py
    goto finished
)

where python >nul 2>nul
if not errorlevel 1 (
    echo [1/2] Checking and installing requirements...
    python -m pip install -r requirements.txt
    if errorlevel 1 goto install_error
    echo.
    echo [2/2] Starting Zengo...
    python app.py
    goto finished
)

echo Python was not found.
echo Install Python 3 and enable "Add Python to PATH", then run this file again.
goto finished

:install_error
echo.
echo ERROR: Installing Python requirements failed.
echo Check your internet connection and Python installation.

:finished
echo.
echo The window will stay open so you can read any error messages.
pause
