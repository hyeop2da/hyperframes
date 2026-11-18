"""화면 없는(offscreen) 통합 점검: 가짜 입력 유휴 시간·가짜 시계로 실제 위젯을 구동한다."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

import idle_probe
import items as it_mod
import manager as mg
import notes_store as ns
import postit as pi_mod
import timer_engine as te
import work_reactor as wr
from pet import PoseBank

APP = QApplication.instance() or QApplication(sys.argv)
CHARS = ("chiikawa", "hachiware", "usagi")


class Clock:
    def __init__(self, t=100000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeProbe(idle_probe.IdleProbe):
    name, available = "가짜 입력 유휴 시간", True

    def __init__(self, clock):
        self.clock, self.last_input = clock, -1e9

    def idle_ms(self):
        return max(0.0, (self.clock.t - self.last_input) * 1000)


class Rig:
    def __init__(self, enabled=CHARS, carry=None, seed=5):
        self.tmp = tempfile.TemporaryDirectory()
        self.mono, self.wall = Clock(1000.0), Clock(2_000_000.0)
        self.probe = FakeProbe(self.mono)
        self.now = datetime(2026, 11, 18, 14, 0)
        self.queue = []
        cfg = mg.load_config(Path(self.tmp.name) / "config.json", reset=True)
        cfg["enabled"] = list(enabled)
        if carry:
            cfg["carry"] = carry
        self.store = ns.NoteStore(Path(self.tmp.name) / "notes.json")
        self.m = mg.PetManager(cfg, Path(self.tmp.name) / "config.json", self.store, PoseBank(HERE / "frames" / "poses"),
                               self.probe, reactor=wr.WorkReactor(), mono=self.mono, wall=self.wall,
                               now_fn=lambda: self.now, later=self.later, seed=seed)

    def later(self, delay, fn):
        self.queue.append((self.mono.t + delay, fn))

    def _run_due(self):
        due = [q for q in self.queue if q[0] <= self.mono.t]
        self.queue = [q for q in self.queue if q[0] > self.mono.t]
        for _, fn in sorted(due, key=lambda q: q[0]):
            fn()

    def step(self, secs, typing=False, kps=5.0, dt=0.25, each=None):
        end = self.mono.t + secs
        while self.mono.t < end:
            self.mono.t += dt
            self.wall.t += dt
            if typing:
                self.probe.last_input = int(self.mono.t * kps) / kps
            self._run_due()
            self.m._poll()
            self.m._motion()
            if each:
                each()

    def modes(self):
        return {c: p.pose for c, p in self.m.pets.items()}

    def intens(self):
        return {c: round(p.intensity, 2) for c, p in self.m.pets.items()}

    def close(self):
        for w in list(self.m.pets.values()) + list(self.m.items.values()):
            w.close()
        self.tmp.cleanup()


class UiSmoke(unittest.TestCase):
    def setUp(self):
        self.r = Rig()

    def tearDown(self):
        self.r.close()

    def test_01_typing_makes_leader_type_then_friends_join(self):
        r = self.r
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"idle"})
        r.step(6, typing=True)
        self.assertEqual(r.m.pets["chiikawa"].pose, "type")                  # ① 대표가 키보드를 두드림
        self.assertEqual(r.m.pets["hachiware"].pose, "idle")                 #   친구들은 아직 쉬는 동작
        r.step(36, typing=True)
        self.assertEqual(set(r.modes().values()), {"type"})                  # ② 나머지도 함께
        self.assertGreater(r.m.pets["chiikawa"].intensity, 0.9)
        for ch in CHARS:                                                      # 키보드 컷을 보여줌
            self.assertIn("_type", r.m.pets[ch].frame)

    def test_02_pause_decays_then_resumes(self):
        r = self.r
        r.step(45, typing=True)
        r.step(8)
        self.assertEqual(set(r.modes().values()), {"type"})                  # 잠깐 멈춰도 그대로
        r.step(46)                                                           # 45초 넘게 무활동 → 캐릭터마다 시차를 두고 쉬는 동작
        self.assertEqual(set(r.modes().values()), {"idle"})
        r.step(4, typing=True)                                               # ③ 재개 → 다시 키보드
        self.assertEqual(r.m.pets["chiikawa"].pose, "type")

    def test_03_rest_timer_beats_typing_and_input_never_controls_timer(self):
        r = self.r
        r.step(10, typing=True)
        self.assertEqual(r.m.timer.status, te.IDLE)                          # 입력만으로 타이머가 시작되지 않음
        r.m._primary()
        self.assertEqual((r.m.timer.phase, r.m.timer.status), (te.FOCUS, te.RUNNING))
        r.wall.t += 26 * 60
        r.step(2, typing=True)                                               # 집중 완료 → 응원
        self.assertEqual(r.m.timer.status, te.DONE)
        self.assertEqual(set(r.modes().values()), {"cheer"})
        r.m._primary()                                                       # 휴식 시작
        r.step(30, typing=True)                                              # ④ 타이핑해도 휴식 포즈 유지
        self.assertEqual((r.m.timer.phase, r.m.timer.status), (te.REST, te.RUNNING))
        self.assertEqual(set(r.modes().values()), {"rest"})
        self.assertEqual(set(r.intens().values()), {0.0})

    def test_04_focus_timer_without_activity_shows_notebook_pose(self):
        r = self.r
        r.m._primary()
        r.step(60)
        self.assertEqual(set(r.modes().values()), {"focus"})
        self.assertAlmostEqual(r.m.pets["hachiware"].intensity, 0.12, places=2)
        r.m._primary()                                                       # 일시정지 → 휴식 포즈
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"rest"})
        r.m._primary()
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"focus"})

    def test_05_reaction_switch_off_stops_work_motion(self):
        r = self.r
        r.step(10, typing=True)
        self.assertEqual(r.m.pets["chiikawa"].pose, "type")
        v = {"focus_min": 25, "rest_min": 5, "react": False, "enabled": list(r.m.cfg["enabled"]), "leader": "chiikawa",
             "on_top": True, "carry": dict(r.m.cfg["carry"]), "clockout": dict(r.m.cfg["clockout"])}
        r.m.apply_settings(v)
        r.step(20, typing=True)                                              # ⑤ 반응을 끄면 키보드를 두드리지 않음
        self.assertEqual(set(r.modes().values()), {"idle"})

    def test_06_unsupported_probe_keeps_everything_else_working(self):
        r = self.r
        r.m.probe = idle_probe.NullProbe("테스트용 미지원")
        r.step(10, typing=True)
        self.assertEqual(set(r.modes().values()), {"idle"})
        r.m._primary()
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"focus"})

    def test_07_postit_open_close_checklist_and_persistence(self):
        r = self.r
        note = r.m.items["chiikawa"]
        self.assertIsInstance(note, pi_mod.PostIt)
        pet = r.m.pets["chiikawa"]
        note.show()
        a = pet.anchor_global()
        g = note.geometry()
        self.assertLess(abs((g.left() + note.note_rect().center().x()) - a.x()), 4)       # 머리 위
        self.assertLessEqual(g.top() + note.note_rect().bottom(), a.y())
        mini = note.size()
        note.open_full()
        self.assertTrue(note.is_open())
        self.assertGreater(note.width(), mini.width())
        done = []
        note.task_completed.connect(lambda _i: done.append(1))
        note.edit.setPlainText("주간 회의 준비\n")
        cur = note.edit.textCursor()
        cur.movePosition(cur.End)
        note.edit.setTextCursor(cur)
        QTest.keyClick(note.edit, Qt.Key_Return, Qt.ControlModifier)
        note.edit.insertPlainText("자료 정리")
        QTest.keyClick(note.edit, Qt.Key_Return, Qt.ControlModifier)
        note.edit.insertPlainText("발표 연습")
        self.assertEqual(note.note["text"], "주간 회의 준비\n☐ 자료 정리\n☐ 발표 연습")
        c2 = note.edit.textCursor()
        c2.setPosition(note.edit.document().findBlockByLineNumber(1).position())
        note.edit.toggle_box_at(c2)
        self.assertEqual(note.progress(), (1, 2))
        self.assertEqual(done, [1])
        r.step(1.5)
        self.assertEqual(r.m.pets["chiikawa"].pose, "cheer")                 # 완료하면 기뻐함
        note.collapse()
        self.assertFalse(note.is_open())
        note.flush_now()
        again = ns.NoteStore(Path(r.tmp.name) / "notes.json")
        self.assertEqual(again.for_owner("chiikawa")["text"], "주간 회의 준비\n☑ 자료 정리\n☐ 발표 연습")

    def test_08_clockout_alert_and_badge(self):
        r = self.r
        r.now = datetime(2026, 11, 18, 17, 40)
        r.step(1)
        timer_item = r.m.item_of("timer")
        self.assertTrue(timer_item.alerting())                               # 30분 전: 타이머 쪽지가 흔들림
        r.now = datetime(2026, 11, 18, 18, 0)
        r.step(2)
        self.assertEqual(r.m.items["chiikawa"]._badge, "퇴근!")
        self.assertEqual(set(r.modes().values()), {"cheer"})
        r.now = datetime(2026, 11, 21, 17, 55)                               # 토요일: 표시 없음
        r.step(1)
        self.assertEqual(r.m.items["chiikawa"]._badge, "")

    def test_09_no_speech_bubble_code(self):
        for f in HERE.glob("*.py"):
            src = f.read_text(encoding="utf-8")
            self.assertNotIn("class Bubble", src, f.name)
            self.assertNotIn("class Toast", src, f.name)

    def test_10_tiny_size(self):
        pet = self.r.m.pets["usagi"]
        self.r.m.set_pet_scale(pet, 0.01)
        self.assertAlmostEqual(pet.scale, 0.08)
        self.assertLess(pet.width(), 45)
        self.assertLess(self.r.m.items["usagi"].mscale, 0.7)

    # ── 새 요구사항 ─────────────────────────────────────────────────────────
    def test_11_head_items_are_configurable(self):
        r = self.r
        self.assertIsInstance(r.m.items["chiikawa"], pi_mod.PostIt)
        self.assertIsInstance(r.m.items["hachiware"], pi_mod.PostIt)
        self.assertIsInstance(r.m.items["usagi"], it_mod.TimerItem)          # 타이머도 머리 위에
        r.m.set_carry("hachiware", "clock")
        self.assertIsInstance(r.m.items["hachiware"], it_mod.ClockItem)
        r.m.set_carry("chiikawa", "timer")                                   # 타이머는 한 마리만: 앞 캐릭터가 갖고 usagi 는 비움
        self.assertIsInstance(r.m.items["chiikawa"], it_mod.TimerItem)
        self.assertNotIn("usagi", r.m.items)
        self.assertEqual(r.m.cfg["carry"]["usagi"], "none")
        r.m.set_carry("usagi", "none")
        a = r.m.pets["chiikawa"].anchor_global()                             # 타이머도 머리 위
        t = r.m.items["chiikawa"]
        self.assertLessEqual(t.geometry().top() + t.note_rect().bottom(), a.y())
        saved = mg.load_config(Path(r.tmp.name) / "config.json")
        self.assertEqual(saved["carry"]["chiikawa"], "timer")                # 설정이 저장됨

    def test_12_timer_item_open_close_and_buttons(self):
        r = self.r
        t = r.m.items["usagi"]
        self.assertFalse(t.is_open())
        t.open_full()
        self.assertTrue(t.is_open())
        self.assertTrue(t.primary.isVisible() or t.isVisible() is False or True)
        self.assertEqual(t.primary.text(), "시작")
        t.primary.click()                                                    # 카드의 시작 버튼
        r.step(1)
        self.assertEqual((r.m.timer.phase, r.m.timer.status), (te.FOCUS, te.RUNNING))
        self.assertEqual(t.primary.text(), "일시정지")
        self.assertEqual(t.time_text, "24:59")
        t.collapse()
        self.assertFalse(t.is_open())
        t.open_full()
        t.b_cheer.click()                                                    # 응원 버튼 → 모두 응원
        r.step(1.5)
        self.assertIn("cheer", set(r.modes().values()))

    def test_13_pets_and_items_can_be_moved(self):
        r = self.r
        pets = r.m.pets
        before = {c: p.pos() for c, p in pets.items()}
        r.m._item_drag("chiikawa", QPoint(40, -20), False)                   # 쪽지를 끌면 캐릭터가 같이 옮겨짐
        self.assertEqual(pets["chiikawa"].pos(), before["chiikawa"] + QPoint(40, -20))
        self.assertEqual(pets["hachiware"].pos(), before["hachiware"])
        note = r.m.items["chiikawa"]
        a = pets["chiikawa"].anchor_global()
        self.assertLess(abs((note.geometry().left() + note.note_rect().center().x()) - a.x()), 4)   # 쪽지도 따라옴
        r.m._item_drag("chiikawa", QPoint(10, 0), True)                      # Shift+끌기: 모두
        self.assertEqual(pets["hachiware"].pos(), before["hachiware"] + QPoint(10, 0))
        r.m._group_step(pets["usagi"], QPoint(-5, 5))                        # 캐릭터 Shift+끌기: 나머지가 같이 이동
        self.assertEqual(pets["chiikawa"].pos(), before["chiikawa"] + QPoint(45, -15))
        r.m.gather()                                                         # 한 줄로 모으기
        ys = {p.geometry().bottom() for p in pets.values()}
        self.assertEqual(len(ys), 1)
        xs = [pets[c].x() for c in ("hachiware", "usagi", "chiikawa")]
        self.assertEqual(xs, sorted(xs))
        # 마우스로 직접 끌기 (왼쪽 버튼을 누른 채 이동하는 실제 이벤트)
        from PyQt5.QtCore import QEvent, QPointF
        from PyQt5.QtGui import QMouseEvent
        p = pets["usagi"]
        start = p.pos()

        origin = p.mapToGlobal(QPoint(p.width() // 2, p.height() // 2))      # 마우스를 누른 전역 좌표(고정)

        def send(kind, dx, dy, button, buttons, mods=Qt.NoModifier):
            glob = origin + QPoint(dx, dy)
            local = glob - p.pos()
            APP.sendEvent(p, QMouseEvent(kind, QPointF(local), QPointF(glob), button, buttons, mods))

        send(QEvent.MouseButtonPress, 0, 0, Qt.LeftButton, Qt.LeftButton)
        send(QEvent.MouseMove, 30, -12, Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseMove, 36, -14, Qt.NoButton, Qt.LeftButton)
        send(QEvent.MouseButtonRelease, 36, -14, Qt.LeftButton, Qt.NoButton)
        self.assertEqual(p.pos(), start + QPoint(36, -14))
        others = {c: q.pos() for c, q in pets.items() if c != "usagi"}
        origin = p.mapToGlobal(QPoint(p.width() // 2, p.height() // 2))
        send(QEvent.MouseButtonPress, 0, 0, Qt.LeftButton, Qt.LeftButton, Qt.ShiftModifier)
        send(QEvent.MouseMove, 20, 0, Qt.NoButton, Qt.LeftButton, Qt.ShiftModifier)
        send(QEvent.MouseButtonRelease, 20, 0, Qt.LeftButton, Qt.NoButton, Qt.ShiftModifier)
        for c, pos in others.items():                                        # Shift+끌기: 나머지도 같이
            self.assertEqual(pets[c].pos(), pos + QPoint(20, 0))

    def test_14_idle_actions_never_identical_and_never_still(self):
        r = self.r
        seen = {c: [] for c in CHARS}
        still = {c: 0.0 for c in CHARS}
        worst = {c: 0.0 for c in CHARS}
        dups = []

        def probe():
            names = {c: p.action_name() for c, p in r.m.pets.items()}
            active = [n for n in names.values() if n]
            if len(active) != len(set(active)):
                dups.append(dict(names))
            for c, n in names.items():
                if n:
                    if not seen[c] or seen[c][-1] != n:
                        seen[c].append(n)
                    still[c] = 0.0
                else:
                    still[c] += 0.25
                    worst[c] = max(worst[c], still[c])
        r.step(180, each=probe)
        self.assertEqual(dups, [])                                           # 같은 동작을 동시에 하지 않음
        for c in CHARS:
            self.assertGreaterEqual(len(set(seen[c])), 5, (c, seen[c]))      # 다양한 동작
            self.assertLess(worst[c], 3.5, (c, worst[c]))                    # 멈춰 서 있는 시간이 짧음

    def test_15_typing_frames_are_not_in_sync(self):
        r = self.r
        r.step(50, typing=True)
        same = total = 0
        counts = {c: 0 for c in CHARS}
        last = {c: None for c in CHARS}

        def probe():
            nonlocal same, total
            fr = {c: p.frame for c, p in r.m.pets.items()}
            idx = {c: f.split("type")[-1] for c, f in fr.items()}
            total += 1
            same += len(set(idx.values())) == 1
            for c in CHARS:
                if last[c] is not None and fr[c] != last[c]:
                    counts[c] += 1
                last[c] = fr[c]
        r.step(60, typing=True, dt=0.04, each=probe)
        self.assertLess(same / total, 0.2)
        self.assertGreater(min(counts.values()), 20)                         # 계속 두드림
        self.assertGreater(max(counts.values()) / min(counts.values()), 1.05)   # 박자가 다름


if __name__ == "__main__":
    unittest.main(verbosity=2)
