@echo off
chcp 65001 >nul
REM 먼작귀 응원 위젯 — Windows 실행 파일(.exe) 하나 만들기 (이 PC에서만 만든다)
REM  - packs\pochacco 폴더(포차코 팩)가 있으면 exe 안에 함께 넣는다. 그림은 저장소에 올리지 않는다.
REM  - 결과: dist\ChiikawaDesk.exe
setlocal
cd /d "%~dp0"
set PY=
py -3 --version >nul 2>nul && set PY=py -3
if not defined PY ( python --version >nul 2>nul && set PY=python )
if not defined PY (
  echo Python 이 없어서 설치를 시도합니다. 설치가 끝나면 이 창을 닫고 다시 실행해 주세요.
  winget install -e --id Python.Python.3.11 --accept-source-agreements --accept-package-agreements
  pause
  exit /b 1
)
%PY% -m venv .venv || goto :fail
.venv\Scripts\python -m pip install --quiet --upgrade pip pyinstaller PyQt5 || goto :fail
echo BUILD = "local"> build_info.py
set ADD=--add-data "frames\poses;frames\poses" --add-data "ui;ui"
if exist "packs\pochacco\manifest.json" set ADD=%ADD% --add-data "packs\pochacco;packs\pochacco"
.venv\Scripts\python -m PyInstaller --noconfirm --clean --onefile --noconsole --name ChiikawaDesk %ADD% chiikawa_desk.py || goto :fail
echo.
echo 완료: %~dp0dist\ChiikawaDesk.exe
if /i not "%1"=="nopause" pause
exit /b 0
:fail
echo.
echo 실패했습니다. 위의 메시지를 그대로 알려 주세요.
pause
exit /b 1
