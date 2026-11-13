@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  exit /b 1
)
call ".venv\Scripts\activate.bat"
set QUALITY_API_TOKEN=local-development-token
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
