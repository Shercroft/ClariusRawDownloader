@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo Building Clarius RAW Data Downloader for Windows
echo ============================================================

where py >nul 2>nul
if errorlevel 1 (
    echo ERROR: Python's Windows launcher ^("py"^) was not found.
    echo Install 64-bit Python 3.12 on this BUILD computer, then retry.
    pause
    exit /b 1
)

if not exist ".build-venv\Scripts\python.exe" (
    echo Creating isolated build environment...
    py -3.12 -m venv .build-venv
    if errorlevel 1 goto :failed
)

call ".build-venv\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 goto :failed
python -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed

set "PLAYWRIGHT_BROWSERS_PATH=%CD%\.playwright-browsers"
set "PLAYWRIGHT_SKIP_BROWSER_GC=1"
python -m playwright install chromium
if errorlevel 1 goto :failed

python -m unittest discover -s tests -v
if errorlevel 1 goto :failed
python app.py --self-test
if errorlevel 1 goto :failed

python -m PyInstaller --clean --noconfirm ClariusRawDownloader.spec
if errorlevel 1 goto :failed

copy /Y "USER_GUIDE.md" "dist\ClariusRawDownloader\USER_GUIDE.md" >nul
"dist\ClariusRawDownloader\ClariusRawDownloader.exe" --self-test
if errorlevel 1 goto :failed

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "if (Test-Path 'dist\ClariusRawDownloader-Windows.zip') { Remove-Item 'dist\ClariusRawDownloader-Windows.zip' -Force }; Compress-Archive -Path 'dist\ClariusRawDownloader\*' -DestinationPath 'dist\ClariusRawDownloader-Windows.zip' -CompressionLevel Optimal"
if errorlevel 1 goto :failed

set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo.
    echo Inno Setup 6 was not found. Installing the installer compiler...
    where winget >nul 2>nul
    if errorlevel 1 (
        echo ERROR: Install Inno Setup 6 from https://jrsoftware.org/isinfo.php
        echo and rerun this build.
        goto :failed
    )
    winget install --id JRSoftware.InnoSetup --exact --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :failed
    set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
    if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
    if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC%" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
    if not exist "%ISCC%" goto :failed
)

"%ISCC%" "installer\ClariusRawDownloader.iss"
if errorlevel 1 goto :failed

echo.
echo BUILD COMPLETE
echo Give Lynn this file:
echo   dist\installer\ClariusRawDownloader-Setup.exe
echo.
echo Lynn double-clicks the installer. She does not need Python.
pause
exit /b 0

:failed
echo.
echo BUILD FAILED. Review the error above.
pause
exit /b 1
