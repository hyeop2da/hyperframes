"""내가 지금 컴퓨터를 쓰고 있는지 알아보는 유휴 시간 조회 (Windows).

마지막 입력이 몇 초 전이었는지 **시간만** 묻는다. 어떤 키를 눌렀는지, 무엇을 입력했는지, 마우스가 어디 있는지,
어떤 프로그램을 쓰는지는 읽지 않으며 후킹도 하지 않는다. Windows 가 아니면 알 수 없음(None)으로 돌려준다.
"""
import sys


def idle_seconds():
    """마지막 키보드·마우스 입력 이후 지난 초. 알 수 없으면 None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return max(0.0, ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0)
    except Exception:
        return None
