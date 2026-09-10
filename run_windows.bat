@echo off
cd /d %~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  py -m venv .venv
  call .venv\Scripts\activate
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  streamlit run app.py
) else (
  echo Python was not found. Install Python 3.11 or newer from python.org, then run this file again.
  pause
)
