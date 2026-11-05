@echo off
rem Opens the app (run exports, settings, history, compare) in the browser.
setlocal
cd /d "%~dp0"

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not installed.
    exit /b 1
)

node -e "process.exit(+process.versions.node.split('.')[0] >= 22 ? 0 : 1)"
if errorlevel 1 (
    for /f %%v in ('node -v') do echo [ERROR] Node.js 22 or later is required ^(found %%v^).
    exit /b 1
)

node -e "require.resolve('exceljs'); require.resolve('postcss'); require.resolve('postcss-selector-parser')" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        exit /b 1
    )
)

node src\app-server.js %*
exit /b %ERRORLEVEL%
