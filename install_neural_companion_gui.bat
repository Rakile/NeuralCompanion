@echo off
setlocal

title Neural Companion GUI Installer

REM Go to the folder where this .bat file is located.
cd /d "%~dp0"

echo ==========================================
echo  Neural Companion GUI Installer
echo ==========================================
echo.

REM Prefer local virtual environment if it exists.
if exist ".venv\Scripts\python.exe" (
    echo Using local virtual environment: .venv
    ".venv\Scripts\python.exe" "install_neural_companion_gui.py"
    goto END
)

REM Fallback to py launcher if available.
where py >nul 2>nul
if %errorlevel%==0 (
    echo Using Windows Python launcher: py
    py -3 "install_neural_companion_gui.py"
    goto END
)

REM Fallback to python command.
where python >nul 2>nul
if %errorlevel%==0 (
    echo Using python from PATH
    python "install_neural_companion_gui.py"
    goto END
)

echo ERROR: Python was not found.
echo Install Python, then run this installer again.
echo The GUI installer will detect Python 3.11 for Neural Companion.
echo.

:END
echo.
echo ==========================================
echo Finished.
echo ==========================================
pause
endlocal
