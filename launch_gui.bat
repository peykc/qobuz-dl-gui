@echo off
setlocal
echo Starting Qobuz-DL GUI...

where qobuz-dl-gui >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    qobuz-dl-gui
) else (
    python -m qobuz_dl.gui_app
)

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Error: Failed to start the GUI. 
    echo Make sure Python and the required dependencies are installed.
    pause
)
