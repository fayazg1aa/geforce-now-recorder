@echo off
setlocal
cd /d "%~dp0"
if not exist ".build-venv\Scripts\python.exe" (
    where py >nul 2>nul
    if errorlevel 1 (
        python -m venv .build-venv
    ) else (
        py -3 -m venv .build-venv
    )
)
if not exist ".build-venv\Scripts\python.exe" goto failed
".build-venv\Scripts\python.exe" -m pip install -r requirements-build.txt
if errorlevel 1 goto failed
".build-venv\Scripts\python.exe" -m PyInstaller --clean --noconfirm --onefile --noconsole --name GeForceNOWRecorder_v1.3 main.py
if errorlevel 1 goto failed
echo.
echo Created: dist\GeForceNOWRecorder_v1.3.exe
pause
exit /b 0
:failed
echo.
echo Build failed. Python 3.10+ and internet access for PyInstaller are required.
pause
exit /b 1
