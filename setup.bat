@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -r backend\requirements.txt -r frontend\requirements.txt
if errorlevel 1 exit /b 1
echo.
echo Setup complete. Start run_api.bat and run_web.bat in separate terminals.
