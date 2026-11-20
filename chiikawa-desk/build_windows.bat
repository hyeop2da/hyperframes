@echo off
rem Build ChiikawaDesk.exe (single file) on this PC. A packs\pochacco folder, if present, is bundled inside.
rem The build runs in an ASCII-only folder (C:\Users\Public\ChiikawaBuild) because PyInstaller fails on non-ASCII paths.
rem Result: dist\ChiikawaDesk.exe (next to this file)
setlocal
echo [1/6] Looking for Python 3.10 - 3.13 ...
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do if not defined PY py -%%V --version >nul 2>nul && set "PY=py -%%V"
if defined PY goto :havepython
echo Python 3.10 - 3.13 was not found. Trying to install Python 3.12 with winget...
winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements
for %%V in (3.12 3.11 3.13 3.10) do if not defined PY py -%%V --version >nul 2>nul && set "PY=py -%%V"
if defined PY goto :havepython
echo.
echo Could not start the freshly installed Python in this window.
echo Close this window and run the file again. If it still fails, install Python 3.12 from https://www.python.org/downloads/
echo (check "Add python.exe to PATH") and run again.
pause
exit /b 1

:havepython
%PY% --version
set "WORK=%PUBLIC%\ChiikawaBuild"
echo [2/6] Copying the files to %WORK% ...
if not exist "%WORK%" mkdir "%WORK%"
robocopy "%~dp0." "%WORK%" /E /XD .venv build dist __pycache__ /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto :fail
cd /d "%WORK%"
echo [3/6] Creating a private environment...
%PY% -m venv .venv
if errorlevel 1 goto :fail
echo [4/6] Installing PyInstaller and PyQt5 (needs internet; the first time takes a few minutes)...
.venv\Scripts\python.exe -m pip install --upgrade pip pyinstaller PyQt5
if errorlevel 1 goto :fail
echo [5/6] Building ChiikawaDesk.exe (a few minutes, lots of messages are normal)...
echo BUILD = "local"> build_info.py
set "ADD=--add-data frames\poses;frames\poses --add-data ui;ui"
if exist "packs\pochacco\manifest.json" set "ADD=%ADD% --add-data packs\pochacco;packs\pochacco"
if exist "packs\kitty\manifest.json" set "ADD=%ADD% --add-data packs\kitty;packs\kitty"
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --noconsole --name ChiikawaDesk %ADD% chiikawa_desk.py
if errorlevel 1 goto :fail
if not exist "%~dp0dist" mkdir "%~dp0dist"
copy /y "%WORK%\dist\ChiikawaDesk.exe" "%~dp0dist\ChiikawaDesk.exe" >nul
if errorlevel 1 goto :fail
echo.
echo [6/6] Done: %~dp0dist\ChiikawaDesk.exe
if /i not "%~1"=="nopause" pause
exit /b 0

:fail
echo.
echo Build failed. Please send the messages above.
pause
exit /b 1
