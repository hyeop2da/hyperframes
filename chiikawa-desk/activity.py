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

    def idle_seconds(self):
        now = self.clock()
        if self.poll_fn():
            self.last = now
        return 1e9 if self.last is None else now - self.last


def _windows_poll():
    import ctypes
    get = ctypes.windll.user32.GetAsyncKeyState

    def poll():
        for vk in KEY_CODES:
            if get(vk) & 0x8001:                # 지금 눌려 있거나, 마지막 확인 뒤에 눌렸다
                return True
        return False
    return poll


_watch = None


def idle_seconds():
    """마지막 키보드 입력 이후 지난 초. 알 수 없으면(Windows 아님·조회 실패) None."""
    global _watch
    if sys.platform != "win32":
        return None
    try:
        if _watch is None:
            _watch = KeyWatch(_windows_poll())
        return _watch.idle_seconds()
    except Exception:
        return None
