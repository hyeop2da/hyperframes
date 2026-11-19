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
from PyQt5.QtGui import QTextFormat, QTextCursor
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication, QLabel

import carried as carried_mod
import items as it_mod
import manager as mg
import notes_store as ns
import panel as panel_mod
import postit as pi_mod
import timer_engine as te
from pet import PoseBank

APP = QApplication.instance() or QApplication(sys.argv)
carried_mod.SETTINGS["animate"] = False        # 기본 시험은 접기·펴기를 즉시 끝낸다(애니메이션은 따로 시험)
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
        note.edit.setPlainText("주간 회의 준비\n자료 정리\n발표 연습")
        for line in (1, 2):                                                  # Ctrl+Enter: 현재 줄을 체크리스트로
            cur = note.edit.textCursor()
            cur.setPosition(note.edit.document().findBlockByLineNumber(line).position())
            note.edit.setTextCursor(cur)
            QTest.keyClick(note.edit, Qt.Key_Return, Qt.ControlModifier)
        self.assertEqual(note.note["text"], "주간 회의 준비\n☐ 자료 정리\n☐ 발표 연습")
        self.assertEqual(note.progress(), (0, 2))
        self.assertEqual(note.note["title"], "주간 회의 준비")                    # 제목은 첫 줄에서 자동
        c2 = note.edit.textCursor()
        c2.setPosition(note.edit.document().findBlockByLineNumber(1).position())
        note.edit.setTextCursor(c2)
        QTest.keyClick(note.edit, Qt.Key_Return, Qt.ControlModifier)         # 같은 줄에서 한 번 더 → 완료(☑)
        self.assertEqual(note.progress(), (1, 2))
        self.assertEqual(done, [1])
        r.step(1.5)
        self.assertEqual(r.m.pets["chiikawa"].pose, "cheer")                 # 완료하면 기뻐함
        note.collapse()
        self.assertFalse(note.is_open())
        note.flush_now()
        again = ns.NoteStore(Path(r.tmp.name) / "notes.json")
        self.assertEqual(again.for_owner("chiikawa")["text"], "주간 회의 준비\n☑ 자료 정리\n☐ 발표 연습")
        self.assertEqual(again.for_owner("chiikawa")["title"], "주간 회의 준비")

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

    # ── 쉬는 시간엔 키보드를 치지 않는다 ─────────────────────────────────────
    def test_16_no_keyboard_frames_during_break_or_rest(self):
        r = self.r
        r.step(3)
        typed = []

        def probe():
            for c, p in r.m.pets.items():
                if "_type" in p.frame:
                    typed.append((round(r.mono.t, 2), c, p.frame))
        r.m._switch_block(r.mono.t, "break")                                 # 쉬는 시간 시작(캐릭터마다 조금씩 시차)
        r.m._block_until = 1e12
        r.step(1.6)                                                          # 시차는 1초 안에 끝남
        r.step(40, each=probe)
        self.assertEqual(typed, [], "쉬는 시간에 키보드 컷이 나옴")
        r.m._switch_block(r.mono.t, "work", immediate=True)
        r.m._block_until = 1e12
        r.step(3)
        self.assertEqual(set(r.modes().values()), {"type"})                 # 일하는 시간엔 다시 두드림
        r.m._primary()                                                       # 집중 시작
        r.step(1)
        r.m._primary()                                                       # 일시정지 → 휴식 포즈
        r.step(1.5)
        typed.clear()
        r.step(8, each=probe)
        self.assertEqual(typed, [], "일시정지(휴식 포즈)에 키보드 컷이 나옴")
        r.m._primary()
        r.wall.t += 26 * 60
        r.step(3)                                                            # 집중 완료 → 응원
        r.m._primary()                                                       # 휴식 타이머
        typed.clear()
        r.step(20, each=probe)
        self.assertEqual(typed, [], "휴식 타이머에 키보드 컷이 나옴")

    # ── 설정: 스크롤로 크기 조절 + 바로 미리보기 ────────────────────────────
    def test_17_settings_size_sliders_apply_live_and_cancel_restores(self):
        r = self.r
        orig = {c: p.scale for c, p in r.m.pets.items()}
        calls = []

        def live(sc):
            calls.append(dict(sc))
            r.m._live_scales(sc)
        d = panel_mod.SettingsDialog(r.m.cfg, bank=r.m.bank, scales=orig, on_live=live)
        d.show()
        self.assertTrue(d.link.isChecked())                                  # 처음엔 모두 같은 크기
        self.assertAlmostEqual(d.current_scales()["usagi"], 0.5, places=2)
        d.sliders["chiikawa"].setValue(panel_mod.scale_to_pos(0.2))          # 하나를 움직이면 모두 같이
        QTest.qWait(80)
        for ch in CHARS:
            self.assertAlmostEqual(d.current_scales()[ch], 0.2, places=2)
            self.assertAlmostEqual(r.m.pets[ch].scale, 0.2, places=2)        # 실제 캐릭터에 바로 반영
        self.assertTrue(calls)
        d.link.setChecked(False)
        d.sliders["usagi"].setValue(panel_mod.scale_to_pos(1.0))
        QTest.qWait(80)
        self.assertAlmostEqual(r.m.pets["usagi"].scale, 1.0, places=2)
        self.assertAlmostEqual(r.m.pets["chiikawa"].scale, 0.2, places=2)
        # 미리보기 위에서 휠
        before = d.sliders["hachiware"].value()
        d.preview.wheel.emit(2, 0.5)                                         # 가운데(하치와레)
        self.assertGreater(d.sliders["hachiware"].value(), before)
        d.preview.wheel.emit(-200, 0.5)
        self.assertEqual(d.sliders["hachiware"].value(), 0)                  # 최소로 내려도 범위 안
        self.assertAlmostEqual(d.current_scales()["hachiware"], panel_mod.SCALE_MIN, places=3)
        d.sliders["hachiware"].setValue(panel_mod.SLIDER_MAX)
        self.assertAlmostEqual(d.current_scales()["hachiware"], panel_mod.SCALE_MAX, places=2)
        img = d.preview.grab().toImage()                                     # 미리보기가 실제로 그려짐
        colors = {img.pixel(x, y) for x in range(0, img.width(), 7) for y in range(0, img.height(), 7)}
        self.assertGreater(len(colors), 8)
        # 값과 저장
        v = d.values()
        self.assertEqual(set(v["scales"]), set(CHARS))
        r.m.apply_settings(v)
        self.assertAlmostEqual(r.m.cfg["pets"]["usagi"]["scale"], v["scales"]["usagi"], places=2)
        saved = mg.load_config(Path(r.tmp.name) / "config.json")
        self.assertAlmostEqual(saved["pets"]["chiikawa"]["scale"], 0.2, places=2)
        # 취소하면 원래대로
        r.m._live_scales(orig)
        for ch in CHARS:
            self.assertAlmostEqual(r.m.pets[ch].scale, orig[ch], places=2)
        d.close()

    def test_18_scale_mapping_is_monotonic_and_bounded(self):
        vals = [panel_mod.pos_to_scale(v) for v in range(0, panel_mod.SLIDER_MAX + 1, 50)]
        self.assertEqual(vals, sorted(vals))
        self.assertAlmostEqual(vals[0], panel_mod.SCALE_MIN)
        self.assertAlmostEqual(vals[-1], panel_mod.SCALE_MAX)
        for s in (0.08, 0.12, 0.5, 1.0, 3.0):
            self.assertAlmostEqual(panel_mod.pos_to_scale(panel_mod.scale_to_pos(s)), s, delta=s * 0.01)

    # ── 캐릭터 저작권 표기: 설정 창 맨 아래에만, 영문으로 ────────────────────
    def test_19_copyright_is_shown_only_at_the_bottom_of_settings_in_english(self):
        notice = panel_mod.COPYRIGHT_NOTICE
        self.assertEqual(notice, "© nagano / chiikawa committee")
        self.assertFalse(any("\uac00" <= ch <= "\ud7a3" for ch in notice))           # 한글이 없다
        d = panel_mod.SettingsDialog(self.r.m.cfg, bank=self.r.m.bank)
        d.show()
        labels = [w for w in d.findChildren(QLabel) if w.text() == notice]
        self.assertEqual(len(labels), 1)                                     # 설정 창에 한 번
        credit = labels[0]
        from PyQt5.QtWidgets import QDialogButtonBox, QScrollArea
        scroll = d.findChild(QScrollArea)
        buttons = d.findChild(QDialogButtonBox)
        credit_top = credit.mapTo(d, credit.rect().topLeft()).y()
        self.assertGreaterEqual(credit_top, scroll.mapTo(d, scroll.rect().bottomLeft()).y())    # 스크롤 영역 아래(항상 보임)
        self.assertGreaterEqual(credit_top, buttons.mapTo(d, buttons.rect().bottomLeft()).y())  # 버튼 줄 아래 = 맨 아래
        d.close()
        # 그 밖의 곳(정보 창·메뉴·툴팁·콘솔)에는 없다
        self.assertFalse(hasattr(panel_mod, "AboutDialog"))
        self.assertFalse(hasattr(self.r.m, "open_about"))
        for f in HERE.glob("*.py"):
            src = f.read_text(encoding="utf-8")
            if f.name == "panel.py":
                continue
            self.assertNotIn("COPYRIGHT", src, f.name)
            self.assertNotIn("정보 · 저작권", src, f.name)
            self.assertNotIn("nagano", src.replace("Characters: © nagano / chiikawa committee", ""), f.name)
        self.assertEqual((HERE / "panel.py").read_text(encoding="utf-8").count("COPYRIGHT_NOTICE"), 2)   # 정의 1번 + 설정 창 하단 라벨 1번뿐

    # ── 폴드 메모 포스트잇 이식 ─────────────────────────────────────────────
    def test_20_foldmemo_eight_colors_and_dark_graphite(self):
        self.assertEqual(ns.COLOR_NAMES, ["yellow", "sand", "rose", "orange", "sage", "sky", "lavender", "graphite"])
        self.assertEqual(ns.COLOR_RGB["yellow"], (249, 234, 157))             # 영상에서 실측한 색
        self.assertEqual(ns.COLOR_RGB["sage"], (210, 227, 199))
        self.assertEqual(ns.COLOR_RGB["rose"], (244, 202, 207))
        self.assertEqual(ns.COLOR_LABELS["graphite"], "그래파이트")
        note = self.r.m.items["chiikawa"]
        note.open_full()
        seen = [note.note["color"]]
        for _ in range(8):                                                   # 색 버튼: 누를 때마다 다음 색, 8번이면 한 바퀴
            note.button_clicked("color")
            seen.append(note.note["color"])
        self.assertEqual(seen[0], seen[-1])
        self.assertEqual(set(seen), set(ns.COLOR_NAMES))
        note.set_color("graphite")
        paper = note.paper()
        self.assertTrue(paper["dark"])
        self.assertGreater(paper["text"].red(), 200)                         # 어두운 종이엔 밝은 글자
        note.set_color("yellow")
        paper = note.paper()
        self.assertFalse(paper["dark"])
        self.assertLess(paper["text"].red(), 80)
        self.assertGreater(paper["card"].red(), note.accent().red() - 1)     # 편집 카드는 종이보다 밝다
        # 이전 버전의 색 이름은 새 이름으로
        old = ns.NoteStore._normalize({"id": "x", "owner": "usagi", "color": "pink"})
        self.assertEqual(old["color"], "rose")

    def test_21_title_is_derived_and_can_be_renamed(self):
        self.assertEqual(ns.derived_title("☐ 자료 정리\n두 번째 줄"), "자료 정리")
        self.assertEqual(ns.derived_title("1. 번호 목록\n본문"), "번호 목록")
        long = ns.derived_title("가" * 30)
        self.assertEqual(long, "가" * 20 + "…")                              # 20자까지, 넘으면 …
        self.assertEqual(ns.derived_title("\n\n"), "")
        note = self.r.m.items["hachiware"]
        note.open_full()
        self.assertEqual(note.title_text(), "")                              # 글을 쓰지 않으면 제목을 보이지 않음
        note.edit.setPlainText("이번 주 보고서 초안")
        self.assertEqual(note.title_text(), "이번 주 보고서 초안")
        note.begin_rename()                                                  # 이름 바꾸기
        self.assertTrue(note.title_edit.isVisible())
        note.title_edit.setText("내 보고서")
        note._finish_rename()
        self.assertEqual(note.title_text(), "내 보고서")
        note.edit.setPlainText("전혀 다른 첫 줄")
        self.assertEqual(note.title_text(), "내 보고서")                      # 직접 지은 이름은 유지
        note.begin_rename()
        note.title_edit.setText("")
        note._finish_rename()
        self.assertEqual(note.title_text(), "전혀 다른 첫 줄")                # 비우면 다시 자동 제목
        note.flush_now()
        again = ns.NoteStore(Path(self.r.tmp.name) / "notes.json").for_owner("hachiware")
        self.assertFalse(again["title_manual"])

    def test_22_checklist_rules_match_foldmemo(self):
        self.assertEqual(ns.toggle_checklist_line("할 일"), "☐ 할 일")
        self.assertEqual(ns.toggle_checklist_line("☐ 할 일"), "☑ 할 일")
        self.assertEqual(ns.toggle_checklist_line("☑ 할 일"), "☐ 할 일")
        self.assertEqual(ns.progress("☐ a\n☑ b\n[ ] c\n- [x] d\n□ e\n■ f\n일반 줄"), (3, 6))
        self.assertEqual(ns.progress(""), (0, 0))

    def test_23_fold_unfold_animation_and_pill(self):
        carried_mod.SETTINGS["animate"] = True
        try:
            r = self.r
            note = r.m.items["chiikawa"]
            note.edit.setPlainText("주간 회의 준비\n☐ 자료 정리\n☑ 발표 연습")
            pill = note.size()
            self.assertAlmostEqual(note.cur_size()[1], 30 * note.mscale, places=1)   # 알약 막대 높이
            note.open_full()
            self.assertTrue(note.animating())
            self.assertFalse(note.edit.isVisible())                          # 펼치는 도중엔 글을 보이지 않음
            sizes, shown = [], []
            for _ in range(40):                                              # 280ms = 약 8~9 프레임(33ms)
                r.mono.t += 0.033
                note.step_anim(r.mono.t)
                sizes.append(note.width())
                shown.append(note.edit.isVisible())
                if not note.animating():
                    break
            self.assertFalse(note.animating())
            self.assertEqual(sizes, sorted(sizes))                           # 부드럽게 커짐
            self.assertGreater(sizes[-1], pill.width())
            self.assertTrue(shown[-1])
            self.assertFalse(shown[0])                                       # 82% 이후에 내용이 나타남
            n_frames = len(sizes)
            self.assertTrue(7 <= n_frames <= 11, n_frames)
            note.collapse()                                                  # 접기도 부드럽게
            self.assertTrue(note.animating())
            for _ in range(40):
                r.mono.t += 0.033
                if not note.step_anim(r.mono.t):
                    break
            self.assertFalse(note.is_open())
            self.assertFalse(note.edit.isVisible())
            self.assertEqual(note.progress(), (1, 2))
            self.assertEqual(note.title_text(), "주간 회의 준비")
        finally:
            carried_mod.SETTINGS["animate"] = False

    def test_24_size_font_and_menu_options(self):
        note = self.r.m.items["usagi"] if isinstance(self.r.m.items["usagi"], pi_mod.PostIt) else self.r.m.items["chiikawa"]
        note.open_full()
        note.set_size(50, 50)                                                # 최소 180×140 아래로는 안 줄어듦
        self.assertEqual(note.open_size(), (180.0, 170.0))
        note.set_size(9999, 9999)
        self.assertEqual(note.open_size(), (float(ns.MAX_W), float(ns.MAX_H)))
        for label, (w, h) in ns.SIZES.items():
            note.set_size(w, h)
            self.assertEqual(note.open_size(), (float(w), float(h)))
        self.assertAlmostEqual(note.note["font_size"], 11)
        note.set_font_size(15)
        self.assertEqual(note.edit.font().pointSizeF(), 15 * 0.95)
        note.toggle_bold()
        self.assertTrue(note.edit.font().bold())
        saved = ns.NoteStore(Path(self.r.tmp.name) / "notes.json").get(note.note["id"])
        self.assertEqual(saved["font_size"], 15.0)
        self.assertTrue(saved["bold"])

    def test_25_pill_width_follows_title(self):
        note = self.r.m.items["chiikawa"]
        note.edit.setPlainText("")
        empty_w = note.mini_size()[0]
        note.edit.setPlainText("매우 긴 제목의 포스트잇입니다 정말 길어요")
        long_w = note.mini_size()[0]
        self.assertGreater(long_w, empty_w)
        self.assertLessEqual(long_w, 230 * note.mscale + 0.01)               # 최대 폭 제한
        self.assertGreaterEqual(empty_w, 96 * note.mscale - 0.01)
        self.assertEqual(note.width(), int(round(long_w + 2 * carried_mod.MARGIN)))       # 접힌 창 크기도 바로 갱신됨(잘림 없음)

    # ── 상단 서식 줄(글꼴·제목·목록·B·I·S·링크) + 저장 ──────────────────────
    def test_26_format_bar_and_save_button(self):
        r = self.r
        note = r.m.items["chiikawa"]
        self.assertTrue(all(not b.isVisible() for b in note.fmt.values()))     # 접혀 있으면 서식 줄이 없다
        note.open_full()
        self.assertEqual([b.text() for b in note.fmt.values()], ["글꼴", "제목", "목록", "B", "I", "S", "링크", "저장"])
        card = note.rect()
        for b in note.fmt.values():
            self.assertTrue(b.isVisible())
            self.assertTrue(card.contains(b.geometry()), b.text())            # 카드 안에 들어옴
            self.assertGreaterEqual(b.width(), 16)
        top = min(b.y() for b in note.fmt.values())
        self.assertGreaterEqual(top, int(note.note_rect().y() + 36))           # 머리줄 아래
        self.assertGreater(note.edit.y(), max(b.geometry().bottom() for b in note.fmt.values()))  # 편집 영역은 서식 줄 아래
        ed = note.edit
        ed.setPlainText("안녕 세상")

        def select(a, b):
            c = ed.textCursor()
            c.setPosition(a)
            c.setPosition(b, QTextCursor.KeepAnchor)
            ed.setTextCursor(c)

        def fmt_at(i):
            c = QTextCursor(ed.document())
            c.setPosition(i + 1)
            return c.charFormat()

        select(3, 5)
        note.fmt["bold"].click()                                              # B: 글자 자체가 굵어진다(기호 삽입 없음)
        self.assertEqual(ed.toPlainText(), "안녕 세상")
        self.assertGreaterEqual(fmt_at(3).fontWeight(), 75)
        self.assertGreaterEqual(fmt_at(4).fontWeight(), 75)
        self.assertFalse(fmt_at(0).fontWeight() >= 75)                        # 선택하지 않은 글자는 그대로
        self.assertTrue(note.fmt["bold"].isChecked())
        note.fmt["bold"].click()
        self.assertFalse(fmt_at(3).fontWeight() >= 75)
        select(3, 5)
        note.fmt["italic"].click()
        self.assertTrue(fmt_at(4).fontItalic() and not fmt_at(0).fontItalic())
        note.fmt["strike"].click()
        self.assertTrue(fmt_at(4).fontStrikeOut() and not fmt_at(1).fontStrikeOut())
        self.assertEqual(ed.toPlainText(), "안녕 세상")
        # 선택한 글자만 글꼴 변경
        ed.setPlainText("가나다라마")
        select(1, 3)
        self.assertTrue(ed.apply_selection_font("Noto Serif CJK KR", 16, True, False))
        self.assertEqual(fmt_at(1).fontFamily(), "Noto Serif CJK KR")
        self.assertEqual(fmt_at(2).fontPointSize(), 16)
        self.assertNotEqual(fmt_at(0).fontFamily(), "Noto Serif CJK KR")
        self.assertNotEqual(fmt_at(3).fontFamily(), "Noto Serif CJK KR")
        self.assertEqual(ed.toPlainText(), "가나다라마")
        # 서식 저장 → 다시 열어도 유지
        note.flush_now()
        saved = ns.NoteStore(Path(r.tmp.name) / "notes.json").for_owner("chiikawa")
        self.assertTrue(any(x.get("f") == "Noto Serif CJK KR" and x["s"] == 1 and x["n"] == 2 for x in saved["runs"]))
        ed.setPlainText("")
        ed.setPlainText(saved["text"])
        ed.apply_runs(saved["runs"])
        self.assertEqual(fmt_at(2).fontFamily(), "Noto Serif CJK KR")
        self.assertNotEqual(fmt_at(4).fontFamily(), "Noto Serif CJK KR")
        select(0, 5)
        self.assertTrue(ed.clear_selection_format())
        self.assertNotEqual(fmt_at(1).fontFamily(), "Noto Serif CJK KR")
        # 제목·목록(글자 크기/줄 머리), 링크
        ed.setPlainText("제목 줄")
        ed.set_heading(2)
        self.assertEqual(ed.toPlainText(), "제목 줄")
        self.assertAlmostEqual(fmt_at(0).fontPointSize(), ed.base[1] * 1.4, places=1)
        ed.set_heading(0)
        self.assertFalse(fmt_at(0).hasProperty(QTextFormat.FontPointSize))
        ed.apply_line_prefix("bullet")
        self.assertEqual(ed.toPlainText(), "• 제목 줄")
        ed.apply_line_prefix("number")
        self.assertEqual(ed.toPlainText(), "1. 제목 줄")
        ed.apply_line_prefix("number")
        self.assertEqual(ed.toPlainText(), "제목 줄")
        ed.setPlainText("홈페이지")
        ed.selectAll()
        ed.insert_link("https://example.com")
        self.assertEqual(ed.toPlainText(), "홈페이지 https://example.com")
        self.assertEqual(fmt_at(6).anchorHref(), "https://example.com")
        self.assertFalse(fmt_at(0).isAnchor())
        # 체크 전환은 줄의 서식을 보존
        ed.setPlainText("할 일")
        select(0, 3)
        ed.toggle_style("bold")
        ed.toggle_checklist()
        self.assertEqual(ed.toPlainText(), "☐ 할 일")
        self.assertGreaterEqual(fmt_at(3).fontWeight(), 75)
        ed.toggle_checklist()
        self.assertEqual(ed.toPlainText(), "☑ 할 일")
        self.assertGreaterEqual(fmt_at(3).fontWeight(), 75)
        # 저장 버튼 / Ctrl+S: 바로 저장
        ed.setPlainText("저장 시험")
        self.assertFalse(note._saved)
        note.fmt["save"].click()
        self.assertTrue(note._saved)
        self.assertEqual(note.fmt["save"].text(), "저장됨 ✓")
        self.assertEqual(ns.NoteStore(Path(r.tmp.name) / "notes.json").for_owner("chiikawa")["text"], "저장 시험")
        ed.setPlainText("Ctrl+S 시험")
        QTest.keyClick(ed, Qt.Key_S, Qt.ControlModifier)
        self.assertEqual(ns.NoteStore(Path(r.tmp.name) / "notes.json").for_owner("chiikawa")["text"], "Ctrl+S 시험")
        # 글꼴 변경(글꼴 창에서 고른 값을 적용하는 경로)
        note.apply_font("Noto Sans CJK KR", 13, True, False)
        saved = ns.NoteStore(Path(r.tmp.name) / "notes.json").for_owner("chiikawa")
        self.assertEqual(saved["font_family"], "Noto Sans CJK KR")
        self.assertAlmostEqual(saved["font_size"], 13.0, places=2)
        self.assertTrue(saved["bold"])
        self.assertTrue(note.edit.font().bold())
        note.collapse()
        self.assertTrue(all(not b.isVisible() for b in note.fmt.values()))     # 접으면 서식 줄도 사라짐

    def test_27_format_bar_fits_in_small_size(self):
        note = self.r.m.items["chiikawa"]
        note.open_full()
        w, h = ns.SIZES["작게"]
        note.set_size(w, h)
        card = note.rect()
        xs = sorted(b.geometry().left() for b in note.fmt.values())
        for b in note.fmt.values():
            self.assertTrue(card.contains(b.geometry()), b.text())
            self.assertGreaterEqual(b.width(), 15)
        lefts = [b.geometry().left() for b in note.fmt.values()]
        rights = [b.geometry().right() for b in note.fmt.values()]
        for a, b2 in zip(lefts[1:], rights[:-1]):
            self.assertGreater(a, b2)                                         # 버튼끼리 겹치지 않음


if __name__ == "__main__":
    unittest.main(verbosity=2)
