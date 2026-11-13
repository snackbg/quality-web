@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.bat first.
  exit /b 1
)
call ".venv\Scripts\activate.bat"
set QUALITY_API_URL=http://127.0.0.1:8001
set QUALITY_API_TOKEN=local-development-token
set DJANGO_DEBUG=true
cd frontend
python manage.py migrate
if errorlevel 1 exit /b 1
python manage.py runserver 127.0.0.1:8000
