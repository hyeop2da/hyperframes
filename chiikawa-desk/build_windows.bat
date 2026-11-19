@echo off
REM 먼작귀 응원 위젯 — Windows 실행 파일(.exe) 만들기 (Python 3.9+ 필요)
cd /d "%~dp0"
python -m pip install --upgrade pip pyinstaller PyQt5
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name ChiikawaDesk ^
  --add-data "frames\poses;frames\poses" --add-data "ui;ui" chiikawa_desk.py
echo.
echo 완료: dist\ChiikawaDesk.exe
pause
