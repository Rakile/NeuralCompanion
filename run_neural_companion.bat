@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call :maybe_update_from_git
if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment not found.
  echo Run install_neural_companion_gui.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" qt_app.py
endlocal
goto :eof

:maybe_update_from_git
where git >nul 2>&1 || goto :eof
git rev-parse --is-inside-work-tree >nul 2>&1 || goto :eof
git remote get-url origin >nul 2>&1 || goto :eof
git fetch origin --quiet >nul 2>&1 || goto :eof

set "NC_HEAD="
set "NC_BRANCH="
set "NC_REMOTE="
for /f "delims=" %%i in ('git rev-parse HEAD 2^>nul') do set "NC_HEAD=%%i"
for /f "delims=" %%i in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "NC_BRANCH=%%i"
if not defined NC_HEAD goto :eof
if not defined NC_BRANCH goto :eof
if /I "%NC_BRANCH%"=="HEAD" goto :eof
for /f "delims=" %%i in ('git rev-parse "origin/%NC_BRANCH%" 2^>nul') do set "NC_REMOTE=%%i"
if not defined NC_REMOTE goto :eof
if /I "%NC_HEAD%"=="%NC_REMOTE%" goto :eof

git diff --quiet --ignore-submodules HEAD -- >nul 2>&1
if errorlevel 1 (
  echo.
  echo Update available, but local changes were detected.
  echo Skipping auto-update prompt to avoid touching your worktree.
  goto :eof
)

echo.
echo A newer version of Neural Companion is available.
choice /C YN /N /M "Do you want to update to the latest version? [Y/N] "
if errorlevel 2 goto :eof
git pull --ff-only origin "%NC_BRANCH%"
if errorlevel 1 (
  echo.
  echo Update failed. Launching the current local version instead.
)
goto :eof
