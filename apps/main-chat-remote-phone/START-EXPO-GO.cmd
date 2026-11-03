@echo off
setlocal
cd /d "%~dp0"
call npm run go
if errorlevel 1 (
  echo.
  echo Expo Go stopped with an error. Press any key to close.
  pause >nul
)
endlocal
