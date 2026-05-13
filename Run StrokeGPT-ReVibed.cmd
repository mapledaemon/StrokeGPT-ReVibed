@echo off
setlocal

cd /d "%~dp0"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if not exist "%PYTHON_EXE%" (
    echo StrokeGPT-ReVibed is not installed yet.
    echo.
    echo Run scripts\install_windows.ps1 first, then double-click this file again.
    echo.
    pause
    exit /b 1
)

set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "STROKEGPT_OPEN_BROWSER=1"

echo Starting StrokeGPT-ReVibed...
echo Leave this window open while using the app.
echo.

"%PYTHON_EXE%" app.py
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if not "%EXIT_CODE%"=="0" (
    echo StrokeGPT-ReVibed stopped with exit code %EXIT_CODE%.
    echo Check the messages above, then rerun scripts\install_windows.ps1 if dependencies are missing.
) else (
    echo StrokeGPT-ReVibed stopped.
)
echo.
pause
exit /b %EXIT_CODE%
