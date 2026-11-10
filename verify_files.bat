@echo off
setlocal
title Verify Automation Code Validator

echo ========================================
echo  Automation Code Validator
echo   Environment Check
echo ========================================
echo.

cd /d "%~dp0"
if errorlevel 1 (
    echo [ERROR] Could not access the project directory.
    pause
    exit /b 1
)

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"

echo Checking Python...
"%PYTHON%" --version
if errorlevel 1 (
    echo [ERROR] Python was not found. Install Python or create the project .venv.
    pause
    exit /b 1
)

echo.

echo Checking application dependencies...
"%PYTHON%" -c "import flask, requests, langgraph, pydantic, langchain_core"
if errorlevel 1 (
    echo [ERROR] Required dependencies are missing.
    echo         Install them with: "%PYTHON%" -m pip install -e .
    pause
    exit /b 1
)

echo.

echo Checking server files...
if exist web_ui\app.py (
    echo [OK] web_ui\app.py
) else (
    echo [ERROR] web_ui\app.py not found.
    pause
    exit /b 1
)

if exist web_ui\templates\index.html (
    echo [OK] web_ui\templates\index.html
) else (
    echo [ERROR] web_ui\templates\index.html not found.
    pause
    exit /b 1
)

if not exist server\start_server.cmd (
    echo [ERROR] server\start_server.cmd not found.
    pause
    exit /b 1
)

echo.
echo [OK] Environment is ready.
echo Start the application with server\start_server.cmd.
pause