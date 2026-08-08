@echo off
REM Double-click this any time you're told there's an update available.
REM It downloads the latest project files from GitHub and replaces them
REM in place - your credentials.json, token.json, PDFs, and import
REM history are never touched.

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0update.ps1"
echo.
pause
