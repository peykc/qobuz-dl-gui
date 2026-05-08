@echo off
setlocal
cd /d "%~dp0"
echo Starting Qobuz-DL GUI...

where python >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    python -m qobuz_dl.gui_app
) else (
    py -m qobuz_dl.gui_app
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Error: Failed to start the GUI. 
    echo Make sure Python and the required dependencies are installed.
    pause
)
