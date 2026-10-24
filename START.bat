@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
    for /f "delims=" %%P in ('where python.exe 2^>nul') do if not defined PYTHON_EXE set "PYTHON_EXE=%%P"
)

if not defined PYTHON_EXE (
    echo Python was not found. Install Python 3.10 or 3.11 and run INSTALL.bat.
    pause
    exit /b 1
)

"%PYTHON_EXE%" -c "import flet, flet_desktop, requests, colr, InquirerPy, websockets, pypresence, rich, winotify, yaml, nest_asyncio" >nul 2>&1
if errorlevel 1 (
    echo Application dependencies are missing or could not be loaded.
    echo Run INSTALL.bat, then try START.bat again.
    echo.
    "%PYTHON_EXE%" -c "import flet, flet_desktop, requests, colr, InquirerPy, websockets, pypresence, rich, winotify, yaml, nest_asyncio"
    pause
    exit /b 1
)

for %%P in ("%PYTHON_EXE%") do set "PYTHONW_EXE=%%~dpPpythonw.exe"
if not exist "%PYTHONW_EXE%" (
    echo pythonw.exe was not found next to python.exe.
    pause
    exit /b 1
)
start "" /B "%PYTHONW_EXE%" "%~dp0gui_main.py"
exit /b 0
