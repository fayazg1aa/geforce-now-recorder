@echo off
setlocal
cd /d "%~dp0"
if exist "GeForceNOWRecorder_v1.3.exe" (
    start "" "GeForceNOWRecorder_v1.3.exe"
    exit /b
)
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 main.py
) else (
    python main.py
)
if errorlevel 1 (
    echo.
    echo Could not start. Use the included EXE, or install Python 3.10+ with Tkinter.
    pause
)
endlocal
