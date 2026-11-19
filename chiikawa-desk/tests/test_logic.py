import ast
import random
import sys
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import clock_out


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class ClockOutTests(unittest.TestCase):
    sch = clock_out.Schedule(time="18:00")

    def st(self, y, m, d, hh, mm, sch=None):
        return clock_out.status(datetime(y, m, d, hh, mm), sch or self.sch)

    def test_phases_on_weekday(self):               # 2026-11-18 = 수요일
        self.assertEqual(self.st(2026, 11, 18, 14, 0)[0], clock_out.FAR)
        self.assertEqual(self.st(2026, 11, 18, 17, 30)[0], clock_out.WARN30)
        self.assertEqual(self.st(2026, 11, 18, 17, 49)[0], clock_out.WARN30)
        self.assertEqual(self.st(2026, 11, 18, 17, 50)[0], clock_out.WARN10)
        self.assertEqual(self.st(2026, 11, 18, 18, 0)[0], clock_out.NOW)
        self.assertEqual(self.st(2026, 11, 18, 18, 4)[0], clock_out.NOW)
        self.assertEqual(self.st(2026, 11, 18, 18, 5)[0], clock_out.OVER)

    def test_weekend_disabled_and_skip(self):       # 2026-11-21 = 토요일
        self.assertEqual(self.st(2026, 11, 21, 17, 55)[0], clock_out.OFF)
        s = clock_out.Schedule(enabled=False)
        self.assertEqual(self.st(2026, 11, 18, 17, 55, s)[0], clock_out.OFF)
        s = clock_out.Schedule(skip_date="2026-11-18")
        self.assertEqual(self.st(2026, 11, 18, 17, 55, s)[0], clock_out.OFF)

    def test_custom_time_and_days(self):
        s = clock_out.Schedule(time="17:30", days=(5,))
        self.assertEqual(self.st(2026, 11, 21, 17, 0, s)[0], clock_out.WARN30)
        self.assertEqual(self.st(2026, 11, 18, 17, 0, s)[0], clock_out.OFF)

    def test_format(self):
        self.assertEqual(clock_out.format_left(5000), "1:23")
        self.assertEqual(clock_out.format_left(1380), "23분")
        self.assertEqual(clock_out.format_left(581), "9:41")
        self.assertEqual(clock_out.parse_hhmm("bad").hour, 18)


class KeyWatchTests(unittest.TestCase):
    def test_only_key_presses_count_and_nothing_else_is_kept(self):
        import activity
        t = {"now": 100.0}
        down = {"v": False}
        w = activity.KeyWatch(lambda: down["v"], clock=lambda: t["now"])
        self.assertGreater(w.idle_seconds(), 1e6)                      # 아직 키를 누른 적 없음
        down["v"] = True
        self.assertEqual(w.idle_seconds(), 0.0)
        down["v"] = False
        t["now"] = 102.5
        self.assertAlmostEqual(w.idle_seconds(), 2.5)                  # 마지막으로 누른 뒤 지난 시간
        self.assertEqual(set(vars(w)), {"poll_fn", "clock", "last"})   # 시각 하나만 기억(키 종류·내용 없음)
        self.assertNotIn(0x01, activity.KEY_CODES)                     # 마우스 버튼은 보지 않는다
        self.assertNotIn(0x02, activity.KEY_CODES)

    def test_not_windows_returns_none(self):
        import activity
        if sys.platform != "win32":
            self.assertIsNone(activity.idle_seconds())


class AutostartTests(unittest.TestCase):
    class FakeReg:
        HKEY_CURRENT_USER, KEY_READ, KEY_SET_VALUE, REG_SZ = 1, 2, 3, 4
        store = {}

        class _Key:
            def __init__(s, d):
                s.d = d

            def __enter__(s):
                return s.d

            def __exit__(s, *a):
                return False

        def OpenKey(self, *a):
            return self._Key(self.store)

        CreateKeyEx = OpenKey

        def QueryValueEx(self, k, name):
            if name not in k:
                raise FileNotFoundError
            return k[name], 1

        def SetValueEx(self, k, name, _r, _t, val):
            k[name] = val

        def DeleteValue(self, k, name):
            if name not in k:
                raise FileNotFoundError
            del k[name]

    def test_enable_disable_roundtrip(self):
        import autostart
        reg = self.FakeReg()
        reg.store = {}
        self.assertFalse(autostart.is_enabled(reg))
        self.assertTrue(autostart.set_enabled(True, reg, command='"C:\\x\\ChiikawaDesk.exe"'))
        self.assertTrue(autostart.is_enabled(reg))
        self.assertEqual(reg.store[autostart.VALUE_NAME], '"C:\\x\\ChiikawaDesk.exe"')
        self.assertTrue(autostart.set_enabled(False, reg))
        self.assertFalse(autostart.is_enabled(reg))
        self.assertTrue(autostart.set_enabled(False, reg))            # 이미 꺼져 있어도 오류 없음

    def test_not_windows_is_noop_and_default_is_on(self):
        import autostart
        import manager
        if sys.platform != "win32":
            self.assertFalse(autostart.set_enabled(True))
        self.assertTrue(manager.DEFAULT_CONFIG["autostart"])
        self.assertIn("pythonw" if not getattr(sys, "frozen", False) else "exe", autostart.launch_command().lower() + "pythonw")


class PrivacyTests(unittest.TestCase):
    FORBIDDEN = {"keyboard", "pynput", "mouse", "pyperclip", "psutil", "pygetwindow", "win32gui", "win32api"}

    def test_no_module_reads_user_input(self):
        """입력 내용을 읽는 모듈·후킹이 없다. 허용되는 건 '키가 눌렸는지'만 묻는 activity.py 하나뿐(키 종류는 저장하지 않음)."""
        for f in HERE.glob("*.py"):
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module.split(".")[0]]
                self.assertFalse(self.FORBIDDEN & set(mods), f"{f.name} imports {mods}")
            for token in ("CGEventSource", "XScreenSaver", "SetWindowsHookEx", "GetKeyState", "GetKeyboardState",
                          "GetCursorPos", "GetForegroundWindow", "GetClipboardData"):
                self.assertNotIn(token, src, f"{f.name}: {token}")
            self.assertNotIn("GetLastInputInfo", src, f.name)            # 마우스까지 반응하는 방식은 쓰지 않는다
            if f.name != "activity.py":
                self.assertNotIn("GetAsyncKeyState", src, f.name)
            else:
                self.assertIn("GetAsyncKeyState", src)
        self.assertFalse((HERE / "idle_probe.py").exists())
        self.assertFalse((HERE / "work_reactor.py").exists())


class BehaviorTests(unittest.TestCase):
    CHARS = ("chiikawa", "hachiware", "usagi")

    def setUp(self):
        import json
        meta = json.loads((HERE / "frames" / "poses" / "manifest.json").read_text(encoding="utf-8"))
        self.names = set(meta["poses"])
        self.meta = meta

    def actors(self, seed=3):
        import behaviors as bh
        return {c: bh.IdleActor(c, self.names, random.Random(seed + i), now=0.0) for i, c in enumerate(self.CHARS)}

    def test_idle_never_two_pets_same_action_and_never_standing_still(self):
        acts = self.actors()
        t, step = 0.0, 0.04
        seen = {c: [] for c in self.CHARS}
        standing = {c: 0.0 for c in self.CHARS}
        longest = {c: 0.0 for c in self.CHARS}
        while t < 240:
            names = {}
            for c, a in acts.items():
                peers = {o.name for k, o in acts.items() if k != c and o.name}
                a.update(t, peers)
                names[c] = a.name
                if a.name:
                    if not seen[c] or seen[c][-1] != a.name:
                        seen[c].append(a.name)
                    standing[c] = 0.0
                else:
                    standing[c] += step
                    longest[c] = max(longest[c], standing[c])
            active = [n for n in names.values() if n]
            self.assertEqual(len(active), len(set(active)), f"t={t:.2f} 같은 동작 동시 진행: {names}")
            t += step
        for c in self.CHARS:
            self.assertGreaterEqual(len(set(seen[c])), 6, (c, seen[c]))        # 다양한 동작
            self.assertLess(longest[c], 3.2, (c, longest[c]))                  # 계속 움직임
            for a, b in zip(seen[c], seen[c][1:]):
                self.assertNotEqual(a, b)                                      # 같은 동작을 연달아 하지 않음

    def test_idle_each_character_has_its_own_actions(self):
        acts = self.actors()
        sets = {c: {a.name for a in acts[c].actions} for c in self.CHARS}
        self.assertIn("look-around", sets["chiikawa"])
        self.assertIn("tilt-head", sets["hachiware"])
        self.assertIn("dizzy", sets["usagi"])
        self.assertNotEqual(sets["chiikawa"], sets["hachiware"])
        self.assertNotEqual(sets["hachiware"], sets["usagi"])

    def test_typing_rhythms_differ_between_characters(self):
        import behaviors as bh
        actors = {}
        for i, c in enumerate(self.CHARS):
            frames = [(t["name"], t["busy"]) for t in self.meta["typing"][c]]
            actors[c] = bh.TypingActor(c, frames, random.Random(10 + i), now=0.0)
        changes = {c: 0 for c in self.CHARS}
        last = {c: None for c in self.CHARS}
        same_idx = total = 0
        t = 0.0
        while t < 30:
            cur = {}
            for c, a in actors.items():
                f = a.update(t, 1.0)
                if last[c] is not None and f != last[c]:
                    changes[c] += 1
                last[c], cur[c] = f, f
            idx = {c: cur[c].split("type")[-1] for c in self.CHARS}
            total += 1
            same_idx += len(set(idx.values())) == 1
            t += 0.04
        self.assertGreater(max(changes.values()) / max(1, min(changes.values())), 1.1)   # 박자(속도)가 다름
        self.assertLess(same_idx / total, 0.15)                                         # 같은 컷을 동시에 보여주는 일이 드묾
        for c in self.CHARS:
            self.assertTrue(all(n in self.names for n, _ in [(x["name"], 0) for x in self.meta["typing"][c]]))
