@echo off
setlocal

title NeuralCompanion // Installer Bootstrap

REM Go to the folder where this .bat file is located.
cd /d "%~dp0"

echo ==============================================================
echo  [NC_BOOTSTRAP]  NEURALCOMPANION // INSTALLER MATRIX
echo  [LOCAL-FIRST]   Native QML runtime setup
echo ==============================================================
echo.

REM Use system Python so component environments can be rebuilt safely.
REM Fallback to py launcher if available.
where py >nul 2>nul
if %errorlevel%==0 (
    echo [RUNTIME] Windows Python launcher detected: py
    py -3 "install_neural_companion_gui.py"
    goto END
)

REM Fallback to python command.
where python >nul 2>nul
if %errorlevel%==0 (
    echo [RUNTIME] Python detected on PATH
    python "install_neural_companion_gui.py"
    goto END
)

echo [ERROR] Python was not found.
echo Install Python, then run this installer again.
echo The GUI installer will detect Python 3.11 for Neural Companion.
echo.

:END
echo.
echo ==============================================================
echo  [NC_BOOTSTRAP] Session finished.
echo ==============================================================
endlocal
