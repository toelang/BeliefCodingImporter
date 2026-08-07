@echo off
REM Belief Coding Resource Importer - Windows launcher
REM Creates a virtual environment on first run, installs dependencies,
REM then runs the importer. Safe to double-click; re-run any time to
REM resume an interrupted import.
REM
REM By default this only PLANS the import - it crawls Drive and shows you
REM the exact structure it would create, without uploading anything.
REM Once you've reviewed import_plan.txt and are happy with it, run:
REM     run.bat --execute
REM to actually create the folders and upload the files.

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
if "%~1"=="--execute" (
    echo Starting import - files WILL be uploaded...
) else (
    echo Starting plan-only run - nothing will be uploaded...
)
echo.
"venv\Scripts\python.exe" main.py %*

echo.
echo Run finished. See import_plan.txt (plan mode) or import_log.csv (--execute) for details.
pause
