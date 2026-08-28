@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo ClariusRawDownloader - RUN GUI FROM SOURCE
echo No installer/build is required.
echo ============================================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher "py" was not found.
  echo Install Python 3.12+ from python.org, then run this file again.
  pause
  exit /b 1
)

py -3 -c "import playwright" >nul 2>nul
if errorlevel 1 (
  echo Installing Playwright for source testing...
  py -3 -m pip install "playwright==1.62.0"
  if errorlevel 1 goto :fail
)

py -3 -m playwright install chromium
if errorlevel 1 goto :fail

py -3 app.py
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo Source run failed. Review the error above.
pause
exit /b 1
