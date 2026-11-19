"""내가 지금 키보드를 치고 있는지 알아보기 (Windows).

**어떤 키가 눌렸는지는 보지 않는다**: 글자·숫자·기호 키 중 '하나라도 눌려 있는가'만 확인하고, 마지막으로 눌린 시각만 기억한다.
키 종류·입력 내용·순서는 저장하지도 보내지도 않으며, 마우스(이동·클릭·휠)에는 반응하지 않는다. 후킹도 하지 않는다.
Windows 가 아니면 알 수 없음(None)을 돌려준다.
"""
import sys
import time

# 확인할 키 범위(가상 키 코드): Backspace·Tab·Enter·한/영·Space~F24 와 기호 키. 마우스 버튼(1~6)과 Shift/Ctrl/Alt 단독은 제외.
KEY_CODES = [0x08, 0x09, 0x0D, 0x15, 0x19] + list(range(0x20, 0x88)) + list(range(0xBA, 0xE0))


class KeyWatch:
    """poll_fn() → 지금 키가 눌렸으면 True. 마지막으로 눌린 뒤 지난 초를 계산한다."""

    def __init__(self, poll_fn, clock=time.monotonic):
        self.poll_fn, self.clock = poll_fn, clock
        self.last = None
        self.down = False                       # 직전 확인 때 키가 눌려 있었는가
        self.presses = 0                        # 아직 가져가지 않은 '새로 눌림' 횟수(어떤 키인지는 모른다)

    def idle_seconds(self):
        now = self.clock()
        down = bool(self.poll_fn())
        if down:
            self.last = now
            if not self.down:
                self.presses += 1
        self.down = down
        return 1e9 if self.last is None else now - self.last

    def take_presses(self):
        n, self.presses = self.presses, 0
        return n


def _windows_poll():
    import ctypes
    get = ctypes.windll.user32.GetAsyncKeyState

    def poll():
        for vk in KEY_CODES:
            if get(vk) & 0x8000:                # 지금 눌려 있는 키만 본다('눌린 적 있음' 비트는 PC에 따라 늘 켜져 있어 쓰지 않는다)
                return True
        return False
    return poll


_watch = None


def _get_watch():
    global _watch
    if _watch is None:
        _watch = KeyWatch(_windows_poll())
    return _watch


def idle_seconds():
    """마지막 키보드 입력 이후 지난 초. 알 수 없으면(Windows 아님·조회 실패) None."""
    if sys.platform != "win32":
        return None
    try:
        return _get_watch().idle_seconds()
    except Exception:
        return None


def take_presses():
    """마지막으로 가져간 뒤 키가 새로 눌린 횟수(키 종류는 모름). Windows 가 아니면 0."""
    if sys.platform != "win32":
        return 0
    try:
        return _get_watch().take_presses()
    except Exception:
        return 0


def describe(idle):
    """설정 창에 보여줄 키보드 감지 상태 문장(idle = idle_seconds() 값)."""
    if idle is None:
        return "이 PC에서는 키 입력을 확인할 수 없어 항상 일하는 모습으로 있어요."
    if idle > 1e8:
        return "키 입력 확인 중 — 아직 키를 누르지 않았어요."
    if idle < 1.0:
        return "키 입력 확인 중 — 지금 키를 누르고 있어요."
    return f"키 입력 확인 중 — 마지막 키 입력 {int(idle)}초 전"
