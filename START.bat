@echo off
:: Change directory to batch script path
cd /d "%~dp0"
where pythonw.exe >nul 2>&1
if errorlevel 1 (
    echo pythonw.exe was not found. Reinstall Python with the pythonw component.
    pause
    exit /b 1
)
start "" /B pythonw.exe "%~dp0gui_main.py"
exit /b 0
