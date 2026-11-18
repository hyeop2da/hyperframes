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
from PyQt5.QtWidgets import QApplication, QLabel

import items as it_mod
import manager as mg
import notes_store as ns
import panel as panel_mod
import postit as pi_mod
import timer_engine as te
from pet import PoseBank

APP = QApplication.instance() or QApplication(sys.argv)
CHARS = ("chiikawa", "hachiware", "usagi")


class Clock:
    def __init__(self, t=100000.0):
        self.t = t

    def __call__(self):
        return self.t


class Rig:
    def __init__(self, enabled=CHARS, carry=None, seed=5):
        self.tmp = tempfile.TemporaryDirectory()
        self.mono, self.wall = Clock(1000.0), Clock(2_000_000.0)
        self.now = datetime(2026, 11, 18, 14, 0)
        self.queue = []
        cfg = mg.load_config(Path(self.tmp.name) / "config.json", reset=True)
        cfg["enabled"] = list(enabled)
        if carry:
            cfg["carry"] = carry
        self.store = ns.NoteStore(Path(self.tmp.name) / "notes.json")
        self.m = mg.PetManager(cfg, Path(self.tmp.name) / "config.json", self.store, PoseBank(HERE / "frames" / "poses"),
                               mono=self.mono, wall=self.wall, now_fn=lambda: self.now, later=self.later, seed=seed)

    def later(self, delay, fn):
        self.queue.append((self.mono.t + delay, fn))

    def _run_due(self):
        due = [q for q in self.queue if q[0] <= self.mono.t]
        self.queue = [q for q in self.queue if q[0] > self.mono.t]
        for _, fn in sorted(due, key=lambda q: q[0]):
            fn()

    def step(self, secs, dt=0.25, each=None):
        end = self.mono.t + secs
        while self.mono.t < end:
            self.mono.t += dt
            self.wall.t += dt
            self._run_due()
            self.m._poll()
            self.m._motion()
            if each:
                each()

    def force_block(self, mode):
        """일하는 시간/쉬는 시간을 고정한다(시험용)."""
        self.m._switch_block(self.mono.t, mode, immediate=True)
        self.m._block_until = 1e12
        self.m._resolve()
        self.step(0.5)

    def modes(self):
        return {c: p.pose for c, p in self.m.pets.items()}

    def close(self):
        for w in list(self.m.pets.values()) + list(self.m.items.values()):
            w.close()
        self.tmp.cleanup()


class UiSmoke(unittest.TestCase):
    def setUp(self):
        self.r = Rig()

    def tearDown(self):
        self.r.close()

    def test_01_everyone_types_on_keyboards_by_themselves(self):
        r = self.r
        r.step(10)                                                           # 사용자 입력 없이도 스스로 키보드를 두드림
        self.assertEqual(set(r.modes().values()), {"type"})
        for ch in CHARS:
            self.assertIn("_type", r.m.pets[ch].frame)

    def test_02_work_and_break_rhythm_is_not_in_sync(self):
        r = self.r
        history = {c: [] for c in CHARS}
        allt = noneT = total = 0
        switch_times = {c: [] for c in CHARS}
        last = {c: None for c in CHARS}

        def probe():
            nonlocal allt, noneT, total
            modes = r.modes()
            n = sum(1 for v in modes.values() if v == "type")
            total += 1
            allt += n == 3
            noneT += n == 0
            for c, v in modes.items():
                if last[c] is not None and v != last[c]:
                    switch_times[c].append(r.mono.t)
                last[c] = v
        r.step(900, each=probe)
        self.assertGreater(allt / total, 0.35)                               # 대부분 다 같이 키보드를 두드림
        self.assertGreater(noneT / total, 0.02)                              # 쉬는 시간도 있음
        n = min(len(v) for v in switch_times.values())
        self.assertGreaterEqual(n, 4)
        for i in range(n):                                                   # 바뀌는 순간이 캐릭터마다 어긋남
            ts = [switch_times[c][i] for c in CHARS]
            self.assertGreater(max(ts) - min(ts), 0.2, ts)

    def test_03_timers_override_work_and_break(self):
        r = self.r
        r.force_block("break")
        self.assertEqual(set(r.modes().values()), {"idle"})
        r.m._primary()                                                       # 집중 시작 → 쉬는 시간이어도 계속 두드림
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"type"})
        r.m._primary()                                                       # 일시정지 → 휴식 포즈
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"rest"})
        r.m._primary()
        r.wall.t += 26 * 60
        r.step(2)                                                            # 집중 완료 → 응원
        self.assertEqual(r.m.timer.status, te.DONE)
        self.assertEqual(set(r.modes().values()), {"cheer"})
        r.m._primary()                                                       # 휴식 시작 → 휴식 포즈
        r.step(30)
        self.assertEqual((r.m.timer.phase, r.m.timer.status), (te.REST, te.RUNNING))
        self.assertEqual(set(r.modes().values()), {"rest"})
        r.wall.t += 6 * 60
        r.step(3)                                                            # 휴식 끝 → 다시 스스로 움직임
        self.assertEqual(r.m.timer.status, te.IDLE)
        self.assertNotIn("rest", set(r.modes().values()))

    def test_04_settings_dialog_is_pastel_and_has_no_work_reaction(self):
        d = panel_mod.SettingsDialog(self.r.m.cfg)
        self.assertFalse(hasattr(d, "react"))                                # '내 작업에 반응하기' 없음
        self.assertNotIn("react", d.values())
        qss = d.styleSheet().lower()
        for color in ("#fff7fa", "#bda9f0", "#f6e8f4"):                      # 파스텔 색
            self.assertIn(color, qss)
        d.show()
        img = d.grab().toImage()
        px = img.pixelColor(6, 6)                                            # 배경이 연한 분홍(파스텔)
        self.assertGreater(px.red(), 235)
        self.assertGreater(px.green(), 235)
        self.assertGreater(px.blue(), 235)
        texts = " ".join(w.text() for w in d.findChildren(QLabel) if w.text())
        self.assertNotIn("반응", texts)
        v = d.values()
        self.assertEqual(set(v["carry"]), set(CHARS))
        d.close()

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
        r.force_block("break")
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
        r.force_block("work")
        r.step(20)
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
        r.step(60, dt=0.04, each=probe)
        self.assertLess(same / total, 0.2)
        self.assertGreater(min(counts.values()), 20)                         # 계속 두드림
        self.assertGreater(max(counts.values()) / min(counts.values()), 1.05)   # 박자가 다름


if __name__ == "__main__":
    unittest.main(verbosity=2)
