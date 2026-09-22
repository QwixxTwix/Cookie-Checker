@echo off
chcp 65001 >nul
title Universal Cookie Checker — by idqwixxa
color 5

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from python.org
    pause
    exit /b 1
)

python -c "import requests, colorama" >nul 2>nul
if errorlevel 1 (
    echo [*] Installing dependencies...
    python -m pip install -r requirements.txt
)

python main.py %*
pause