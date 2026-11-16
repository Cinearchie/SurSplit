@echo off
REM One-command start for Windows.
cd /d "%~dp0"

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo FFmpeg is not installed. Run:  winget install Gyan.FFmpeg   then reopen this window.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt

if not exist .env copy .env.example .env >nul
python scripts\download_models.py hq
echo.
echo SurSplit is starting -^> http://127.0.0.1:8000
python -m app.main
