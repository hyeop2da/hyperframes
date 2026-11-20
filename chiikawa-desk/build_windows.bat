@echo off
rem Build ChiikawaDesk.exe (single file) on this PC. A packs\pochacco folder, if present, is bundled inside.
rem Result: dist\ChiikawaDesk.exe
setlocal
cd /d "%~dp0"
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY python --version >nul 2>nul && set "PY=python"
if not defined PY goto :nopython
%PY% -m venv .venv
if errorlevel 1 goto :fail
.venv\Scripts\python.exe -m pip install --quiet --upgrade pip pyinstaller PyQt5
if errorlevel 1 goto :fail
echo BUILD = "local"> build_info.py
set "ADD=--add-data frames\poses;frames\poses --add-data ui;ui"
if exist "packs\pochacco\manifest.json" set "ADD=%ADD% --add-data packs\pochacco;packs\pochacco"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --noconsole --name ChiikawaDesk %ADD% chiikawa_desk.py
if errorlevel 1 goto :fail
echo.
echo Done: %~dp0dist\ChiikawaDesk.exe
if /i not "%~1"=="nopause" pause
exit /b 0

:nopython
echo Python was not found. Trying to install it with winget...
winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
echo.
echo When the install is finished, close this window and run the file again.
pause
exit /b 1

:fail
echo.
echo Build failed. Please send the messages above.
pause
exit /b 1
