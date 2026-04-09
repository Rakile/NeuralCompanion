@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Run install_neural_companion.ps1 first.
  pause
  exit /b 1
)
call ".venv\Scripts\activate.bat"
python qt_app.py
endlocal
