@echo off
REM Cloudflare Telegram Bot - Setup Script for Windows
REM This script automates the installation and setup process on Windows

echo.
echo ============================================================
echo     Cloudflare Telegram Bot - Setup Script (Windows)
echo ============================================================
echo.

REM Check if Python is installed
echo [INFO] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH
    echo Please install Python 3.8 or higher from https://www.python.org/
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [SUCCESS] Python %PYTHON_VERSION% found

REM Check if pip is installed
echo [INFO] Checking pip installation...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] pip is not installed
    pause
    exit /b 1
)
echo [SUCCESS] pip found

REM Install dependencies
echo [INFO] Installing Python dependencies...
if exist requirements.txt (
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Failed to install dependencies
        pause
        exit /b 1
    )
    echo [SUCCESS] Dependencies installed
) else (
    echo [ERROR] requirements.txt not found
    pause
    exit /b 1
)

REM Run installation script
echo [INFO] Running installation wizard...
if exist install.py (
    python install.py
    if errorlevel 1 (
        echo [WARNING] Installation script encountered an error
    ) else (
        echo [SUCCESS] Configuration completed
    )
) else (
    echo [WARNING] install.py not found. You'll need to configure manually.
    echo [INFO] Create a .env file with the following variables:
    echo   TELEGRAM_BOT_TOKEN
    echo   ADMIN_USER_IDS
    echo   CLOUDFLARE_API_TOKEN
    echo   CLOUDFLARE_ZONE_ID
)

echo.
echo [SUCCESS] Setup completed!
echo.
echo [INFO] Next steps:
echo   1. Review your .env file to ensure all settings are correct
echo   2. Run the bot: python bot.py
echo   3. Or run in background: start /b python bot.py ^> output.log 2^>^&1
echo.

pause

