@echo off
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 start.py
  goto :eof
)
where python >nul 2>nul
if %errorlevel%==0 (
  python start.py
  goto :eof
)
echo Python 3 was not found. Please install Python 3.10 or newer.
pause
