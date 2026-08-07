@echo off
REM Belief Coding Resource Importer - Windows launcher
REM Creates a virtual environment on first run, installs dependencies,
REM then runs the importer. Safe to double-click; re-run any time to
REM resume an interrupted import.

setlocal

cd /d "%~dp0"

if not exist "venv\Scripts\python.exe" (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo Could not create a virtual environment. Make sure Python 3.9+ is
        echo installed and available as "python" on your PATH.
        pause
        exit /b 1
    )
)

echo Installing/updating dependencies...
"venv\Scripts\python.exe" -m pip install --upgrade pip >nul
"venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo Failed to install dependencies. See the error above.
    pause
    exit /b 1
)

if not exist "credentials.json" (
    echo.
    echo credentials.json was not found in this folder.
    echo See README.md for how to create one in Google Cloud Console.
    pause
    exit /b 1
)

if not exist "PDFs" (
    mkdir "PDFs"
)

echo.
echo Starting import...
echo.
"venv\Scripts\python.exe" main.py

echo.
echo Import run finished. See import_log.csv for full details.
pause
