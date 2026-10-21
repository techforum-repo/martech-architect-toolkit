
@echo off
setlocal
cd /d "%~dp0"

echo.
echo ======================================
echo Web Technology Inspector - Windows
echo ======================================
echo.

where py >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating Python virtual environment...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

set "PYTHON=.venv\Scripts\python.exe"

echo Checking dependencies...
"%PYTHON%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo Checking Playwright Chromium...
"%PYTHON%" -m playwright install chromium
if errorlevel 1 goto :fail

echo Starting application...
"%PYTHON%" launcher.py

if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Application startup failed.
pause
exit /b 1
