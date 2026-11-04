@echo off
rem Opens the compare page (what changed between two saved exports) in the
rem browser. With arguments, compares on the command line instead:
rem   compare.bat --list
rem   compare.bat <before> <after>
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

node -e "require.resolve('exceljs')" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing dependencies...
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        exit /b 1
    )
)

node src\compare.js %*
exit /b %ERRORLEVEL%
