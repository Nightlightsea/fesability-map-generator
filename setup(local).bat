@echo off
setlocal
cd /d "%~dp0"

echo %DATE% - %TIME%
echo.

rem --- Check Python is available ---
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found on PATH. Install Python and try again.
    goto :fail
)

rem --- Check requirements file exists ---
if not exist requirements.txt (
    echo ERROR: requirements.txt not found in %CD%
    goto :fail
)

rem --- Create venv if needed ---
if exist venv\Scripts\python.exe (
    echo Existing venv found, reusing it.
) else (
    echo Setting up venv...
    python -m venv venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        goto :fail
    )
)
echo.

rem --- Install dependencies ---
echo Installing dependencies...
venv\Scripts\python.exe -m pip install --upgrade pip
venv\Scripts\python.exe -m pip install --require-virtualenv -r requirements.txt
if errorlevel 1 (
    echo ERROR: Dependency installation failed.
    goto :fail
)

echo.
echo Install finished.
echo   Run the app:   run-local.bat
echo   Run the tests: run-tests-local.bat
pause
exit /b 0

:fail
echo.
echo Setup did not complete.
pause
exit /b 1
