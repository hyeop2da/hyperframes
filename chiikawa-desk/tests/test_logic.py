import ast
import random
import sys
import unittest
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import clock_out
import idle_probe
import timer_engine as te
import work_reactor as wr


class FakeClock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


class TimerTests(unittest.TestCase):
    def test_flow_start_pause_resume_done_rest(self):
        clk = FakeClock()
        t = te.PomodoroTimer(25, 5, clock=clk)
        self.assertEqual((t.phase, t.status), (te.FOCUS, te.IDLE))
        t.start_focus()
        clk.advance(600)
        self.assertAlmostEqual(t.remaining(), 900)
        t.pause()
        clk.advance(3600)                       # 멈춘 동안 시간이 흘러도 유지
        self.assertAlmostEqual(t.remaining(), 900)
        t.resume()
        clk.advance(899)
        self.assertIsNone(t.tick())
        clk.advance(2)
        self.assertEqual(t.tick(), te.FOCUS)
        self.assertEqual(t.status, te.DONE)     # 응원 + 휴식 시작 버튼 대기
        t.start_rest()
        self.assertAlmostEqual(t.remaining(), 300)
        clk.advance(301)
        self.assertEqual(t.tick(), te.REST)
        self.assertEqual((t.phase, t.status), (te.FOCUS, te.IDLE))

    def test_restore_running_future_and_past(self):
        clk = FakeClock()
        t = te.PomodoroTimer(25, 5, clock=clk)
        t.start_focus()
        saved = t.to_dict()
        clk.advance(300)                        # 앱을 껐다 켬
        t2 = te.PomodoroTimer(clock=clk)
        self.assertIsNone(t2.restore(saved))
        self.assertEqual(t2.status, te.RUNNING)
        self.assertAlmostEqual(t2.remaining(), 1200)
        clk.advance(5000)                       # 자리를 오래 비움
        t3 = te.PomodoroTimer(clock=clk)
        self.assertEqual(t3.restore(saved), te.FOCUS)
        self.assertEqual(t3.status, te.DONE)

    def test_restore_garbage_is_safe(self):
        t = te.PomodoroTimer(clock=FakeClock())
        t.restore({"status": "??", "end_at": "x"})
        self.assertEqual(t.status, te.IDLE)

    def test_clock_going_backwards_is_clamped(self):
        clk = FakeClock()
        t = te.PomodoroTimer(25, 5, clock=clk)
        t.start_focus()
        clk.advance(-7200)
        self.assertLessEqual(t.remaining(), 25 * 60 + 1)


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


def run_typing(r, t0, secs, kps=5.0, pointer=False, step=0.25):
    """kps 로 타이핑하는 사용자를 흉내 내어 샘플을 먹인다. 이벤트를 모아 돌려준다."""
    ev, t = [], t0
    while t < t0 + secs:
        last_key = int(t * kps) / kps
        r.feed(t, (t - last_key) * 1000, pointer)
        ev += r.update(t)
        t += step
    return ev, t


def run_idle(r, t0, secs, last_input_t, step=0.25):
    ev, t = [], t0
    while t < t0 + secs:
        r.feed(t, (t - last_input_t) * 1000)
        ev += r.update(t)
        t += step
    return ev, t


class ReactorTests(unittest.TestCase):
    def new(self):
        return wr.WorkReactor(rng=random.Random(1))

    def test_1_typing_starts_focus(self):
        r = self.new()
        ev, _ = run_typing(r, 1000.0, 6)
        self.assertEqual(r.state, wr.FOCUS)
        self.assertIn("focus_start", ev)

    def test_single_pointer_move_never_starts(self):
        r = self.new()
        r.feed(1000.0, 100, pointer_moved=True)
        for k in range(1, 80):
            r.feed(1000.0 + k * 0.25, 100 + k * 250, pointer_moved=False)
            self.assertEqual(r.update(1000.0 + k * 0.25), [])
        self.assertEqual(r.state, wr.IDLE)

    def test_pointer_only_needs_much_longer(self):
        r = self.new()
        ev, _ = run_typing(r, 1000.0, 3, kps=2.0, pointer=True)    # 3초 동안 마우스만 흔듦
        self.assertEqual(r.state, wr.IDLE)

    def test_2_continued_work_brings_friends(self):
        r = self.new()
        ev, _ = run_typing(r, 1000.0, 40)
        self.assertEqual(r.state, wr.TOGETHER)
        self.assertIn("together_start", ev)
        self.assertGreater(r.intensity, 0.9)

    def test_3_pause_keeps_then_settles_then_resumes(self):
        r = self.new()
        _, t = run_typing(r, 1000.0, 40)
        last = t - 0.25
        ev, t = run_idle(r, t, 4, last)                  # 4초 쉼: 서서히 잦아드는 중
        self.assertEqual(r.state, wr.TOGETHER)
        self.assertTrue(0.0 < r.intensity < 1.0, r.intensity)
        ev, t = run_idle(r, t, 26, last)                 # 30초 쉼: 포즈·상태는 그대로, 움직임은 거의 멈춤
        self.assertEqual(r.state, wr.TOGETHER)
        self.assertEqual(ev.count("settle"), 0)
        self.assertLess(r.intensity, 0.05)
        ev, t = run_idle(r, t, 20, last)                 # 50초째: 기본으로 돌아감
        self.assertEqual(r.state, wr.IDLE)
        self.assertIn("settle", ev)
        ev, t = run_typing(r, t, 3)                      # 재개: 짧은 시간에도 다시 시작
        self.assertEqual(r.state, wr.FOCUS)
        self.assertIn("focus_start", ev)

    def test_hop_interval_at_least_two_minutes(self):
        r = self.new()
        ev_all, t = [], 1000.0
        hops = []
        end = t + 900
        while t < end:
            ev, t2 = run_typing(r, t, 5)
            hops += [t for e in ev if e == "hop"] and [t]
            ev_all += ev
            t = t2
        times = []
        r2 = self.new()
        t = 1000.0
        while t < end:
            last = int(t * 5) / 5
            r2.feed(t, (t - last) * 1000)
            for e in r2.update(t):
                if e == "hop":
                    times.append(t)
            t += 0.25
        self.assertGreaterEqual(len(times), 2)
        for a, b in zip(times, times[1:]):
            self.assertGreaterEqual(b - a, 120.0)

    def test_none_idle_is_ignored(self):
        r = self.new()
        r.feed(1.0, None)
        self.assertEqual(r.update(1.0), [])


class PrivacyTests(unittest.TestCase):
    FORBIDDEN = {"keyboard", "pynput", "mouse", "pyperclip", "psutil", "pygetwindow", "win32gui"}

    def test_logic_modules_import_no_input_hooks(self):
        for name in ("work_reactor.py", "idle_probe.py", "timer_engine.py", "clock_out.py"):
            tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module.split(".")[0]]
                self.assertFalse(self.FORBIDDEN & set(mods), f"{name} imports {mods}")

    def test_probe_falls_back_gracefully(self):
        p = idle_probe.create_probe()
        self.assertIsInstance(p, idle_probe.IdleProbe)
        if not p.available:
            self.assertTrue(p.reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)


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
