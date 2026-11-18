"""운영체제의 '마지막 입력 후 경과 시간'만 조회한다.

키 이벤트를 받는 후킹(keyboard/pynput 등)을 쓰지 않는다 → 입력한 글자·키 종류·클립보드·
활성 프로그램 이름을 읽을 방법 자체가 없고, 관리자 권한·접근성 권한도 필요 없다(맥은 실제 확인 필요).
"""
import ctypes
import os
import subprocess
import sys


class IdleProbe:
    name = "none"
    available = False
    reason = ""

    def idle_ms(self):
        """마지막 입력(키보드·마우스·스크롤) 후 경과 ms. 조회 실패 시 None."""
        return None


class NullProbe(IdleProbe):
    def __init__(self, reason):
        self.reason = reason


class WindowsProbe(IdleProbe):
    name = "Windows 입력 유휴 시간 (GetLastInputInfo)"

    def __init__(self):
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        self._info = LASTINPUTINFO()
        self._info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        self._user32 = ctypes.windll.user32
        self._kernel32 = ctypes.windll.kernel32
        self.available = True

    def idle_ms(self):
        if not self._user32.GetLastInputInfo(ctypes.byref(self._info)):
            return None
        return (self._kernel32.GetTickCount() - self._info.dwTime) & 0xFFFFFFFF   # 32비트 순환 보정


class MacProbe(IdleProbe):
    name = "macOS 입력 유휴 시간 (CGEventSource)"

    def __init__(self):
        lib = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        fn = lib.CGEventSourceSecondsSinceLastEventType
        fn.restype = ctypes.c_double
        fn.argtypes = [ctypes.c_int32, ctypes.c_uint32]
        self._fn = fn
        self.available = True

    def idle_ms(self):
        # kCGEventSourceStateHIDSystemState = 1, kCGAnyInputEventType = ~0
        return int(self._fn(1, 0xFFFFFFFF) * 1000)


class X11Probe(IdleProbe):
    name = "Linux X11 입력 유휴 시간 (XScreenSaver)"

    def __init__(self):
        x11 = ctypes.CDLL("libX11.so.6")
        xss = ctypes.CDLL("libXss.so.1")

        class XScreenSaverInfo(ctypes.Structure):
            _fields_ = [("window", ctypes.c_ulong), ("state", ctypes.c_int), ("kind", ctypes.c_int),
                        ("til_or_since", ctypes.c_ulong), ("idle", ctypes.c_ulong), ("eventMask", ctypes.c_ulong)]

        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)
        xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XScreenSaverInfo)]
        self._dpy = x11.XOpenDisplay(None)
        if not self._dpy:
            raise OSError("X 디스플레이를 열 수 없습니다")
        self._root = x11.XDefaultRootWindow(self._dpy)
        self._xss, self._info = xss, xss.XScreenSaverAllocInfo()
        self.available = True

    def idle_ms(self):
        if not self._xss.XScreenSaverQueryInfo(self._dpy, self._root, self._info):
            return None
        return int(self._info.contents.idle)


def create_probe():
    """현재 OS에 맞는 조회기를 만든다. 못 만들면 사유를 담은 NullProbe."""
    try:
        if sys.platform.startswith("win"):
            return WindowsProbe()
        if sys.platform == "darwin":
            return MacProbe()
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            return NullProbe("Wayland 세션에서는 입력 유휴 시간을 가져올 수 없습니다 (X11 세션에서 사용해 주세요)")
        return X11Probe()
    except Exception as exc:  # 라이브러리 없음 등
        return NullProbe(f"입력 유휴 시간을 조회할 수 없습니다: {exc}")


def diagnose(seconds=10, interval=0.5):
    """--diagnose-input: 경과 시간을 출력한다. 메모장에서 타이핑하며 0 근처로 떨어지는지 확인."""
    import time
    probe = create_probe()
    print("감지 방식:", probe.name if probe.available else f"사용 불가 — {probe.reason}")
    end = time.time() + seconds
    while time.time() < end and probe.available:
        print(f"마지막 입력 후 {probe.idle_ms() / 1000:6.2f}초", flush=True)
        time.sleep(interval)
