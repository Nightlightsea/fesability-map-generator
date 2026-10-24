@echo off

if not exist venv (
    echo "ERROR: venv folder not found in %CD%."
    echo "Please run setup(local).bat"
    echo.
    pause
    exit
)

"%~dp0venv\Scripts\python.exe" "%~dp0run.py" --run-tests test_files %*
