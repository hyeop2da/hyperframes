"""PC를 켤 때 자동 실행 (Windows: 현재 사용자의 시작 프로그램 레지스트리). 관리자 권한이 필요 없다."""
import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "ChiikawaDesk"


def launch_command():
    """로그인할 때 실행할 명령. 실행 파일(.exe)이면 그대로, 파이썬 소스면 콘솔 없는 pythonw 로."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe")
    exe = pyw if pyw.exists() else py
    return f'"{exe}" "{Path(__file__).resolve().with_name("chiikawa_desk.py")}"'


def _winreg(reg=None):
    if reg is not None:
        return reg
    if sys.platform != "win32":
        return None
    import winreg
    return winreg


def is_enabled(reg=None):
    w = _winreg(reg)
    if w is None:
        return False
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_READ) as k:
            w.QueryValueEx(k, VALUE_NAME)
        return True
    except OSError:
        return False


def set_enabled(on, reg=None, command=None):
    """켜면 시작 프로그램에 등록(경로가 바뀌었으면 갱신), 끄면 제거. 성공하면 True."""
    w = _winreg(reg)
    if w is None:
        return False
    try:
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, RUN_KEY, 0, w.KEY_SET_VALUE) as k:
            if on:
                w.SetValueEx(k, VALUE_NAME, 0, w.REG_SZ, command or launch_command())
            else:
                try:
                    w.DeleteValue(k, VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False
