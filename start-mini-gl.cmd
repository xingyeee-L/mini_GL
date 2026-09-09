@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo mini_GL could not find .venv\Scripts\python.exe
  echo Create the project virtual environment before starting the desktop workspace.
  pause
  exit /b 1
)
set "PYTHONPATH=src"
".venv\Scripts\python.exe" -m mini_gl desktop
