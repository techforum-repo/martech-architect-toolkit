
@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  EWP AEM STYLE SYSTEM EXPORTER
echo ============================================
echo.

where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js is not installed.
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] npm is not installed.
    exit /b 1
)

echo [1/3] Checking required dependencies...

node -e "require.resolve('exceljs'); require.resolve('postcss'); require.resolve('postcss-selector-parser')" >nul 2>&1

if errorlevel 1 (
    echo [INFO] Dependencies missing. Installing automatically...

    call npm install --no-audit --no-fund

    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        exit /b 1
    )
) else (
    echo [OK] Dependencies already installed.
)

echo.
echo [2/3] Running AEM and FE export...
echo.

node src\master-exporter.js
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [3/3] Export finished.

if "%EXIT_CODE%"=="0" (
    echo [SUCCESS] Export completed.
) else (
    if "%EXIT_CODE%"=="2" (
        echo [WARNING] Export completed with validation issues.
    ) else (
        echo [ERROR] Export failed.
    )
)

exit /b %EXIT_CODE%
