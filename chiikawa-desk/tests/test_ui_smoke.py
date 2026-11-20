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
from pack_fixture import make_pack
from pet import POCHACCO_IDS, PoseBank

APP = QApplication.instance() or QApplication(sys.argv)
carried_mod.SETTINGS["animate"] = False        # 기본 시험은 접기·펴기를 즉시 끝낸다(애니메이션은 따로 시험)
CHARS = ("chiikawa", "hachiware", "usagi")


class Clock:
    def __init__(self, t=100000.0):
        self.t = t

    def __call__(self):
        return self.t


class Rig:
    def __init__(self, enabled=CHARS, carry=None, seed=5, pack=False):
        self.tmp = tempfile.TemporaryDirectory()
        self.mono, self.wall = Clock(1000.0), Clock(2_000_000.0)
        self.now = datetime(2026, 11, 18, 14, 0)
        self.idle = 0.0                                  # 마지막 입력 이후 초(시험에서 조절)
        self.presses = 0                                 # 새로 눌린 키 횟수(시험에서 조절)
        self.queue = []
        cfg = mg.load_config(Path(self.tmp.name) / "config.json", reset=True)
        cfg["enabled"] = list(enabled)
        if carry:
            cfg["carry"] = carry
        self.store = ns.NoteStore(Path(self.tmp.name) / "notes.json")
        self.m = mg.PetManager(cfg, Path(self.tmp.name) / "config.json", self.store, PoseBank(HERE / "frames" / "poses", make_pack(Path(self.tmp.name) / "pack") if pack else None),
                               mono=self.mono, wall=self.wall, now_fn=lambda: self.now, later=self.later, seed=seed, idle_fn=lambda: self.idle, press_fn=self._take_presses)

    def _take_presses(self):
        n, self.presses = self.presses, 0
        return n

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
        r.step(900, dt=0.1, each=probe)
        self.assertGreater(allt / total, 0.35)                               # 대부분 다 같이 키보드를 두드림
        self.assertGreater(noneT / total, 0.02)                              # 쉬는 시간도 있음
        n = min(len(v) for v in switch_times.values())
        self.assertGreaterEqual(n, 4)
        spreads = [max(ts) - min(ts) for ts in ([switch_times[c][i] for c in CHARS] for i in range(n))]
        self.assertGreater(sum(s > 0.15 for s in spreads) / n, 0.7, spreads)    # 바뀌는 순간이 캐릭터마다 어긋남
        self.assertLess(max(spreads), 1.3, spreads)                             # 하지만 모두 1초 안팎에 바뀜

    def test_03_keyboard_only_while_i_am_working(self):
        r = self.r
        r.step(3)
        self.assertEqual(set(r.modes().values()), {"type"})                  # 내가 컴퓨터를 쓰는 중 → 함께 일함
        r.idle = 120.0                                                       # 입력이 없어진 지 2분
        r.step(3)
        self.assertEqual(set(r.modes().values()), {"idle"})                  # 키보드를 멈추고 쉬는 동작
        typed = []
        r.step(30, each=lambda: typed.extend(c for c, p in r.m.pets.items() if "_type" in p.frame))
        self.assertEqual(typed, [], "내가 일하지 않는데 키보드 컷이 나옴")
        r.idle = 29 * 60.0                                                   # 29분: 아직 쉬는 동작
        r.step(3)
        self.assertEqual(set(r.modes().values()), {"idle"})
        r.idle = 31 * 60.0                                                   # 30분 넘게 입력 없음 → 모두 차 마시기
        r.step(3)
        self.assertEqual(set(r.modes().values()), {"rest"})
        typed = []
        r.step(10, each=lambda: typed.extend(c for c, p in r.m.pets.items() if "_type" in p.frame))
        self.assertEqual(typed, [])
        r.idle = 2.0                                                         # 다시 입력 → 0.3초 안에 모두 다시 두드림
        r.step(0.3, dt=0.05)
        self.assertEqual(set(r.modes().values()), {"type"})
        r.step(5)
        self.assertEqual(set(r.modes().values()), {"type"})
        r.idle = None                                                        # 알 수 없으면(다른 OS) 계속 일함
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"type"})
        r.m.cfg["follow"]["enabled"] = False                                 # 끄면 입력과 무관하게 일함
        r.idle = 999.0
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"type"})

    def test_03c_reaction_within_one_second_even_during_a_break(self):
        r = self.r
        r.force_block("break")                                              # 쉬는 시간 중
        r.idle = 120.0
        r.step(3)
        r.idle = 0.3                                                         # 입력 시작
        r.step(0.3, dt=0.05)                                                 # 0.3초 안에 반응
        self.assertEqual(set(r.modes().values()), {"type"})

    def test_03d_angled_desk_frames_are_not_used_for_typing(self):
        bank = self.r.m.bank
        for ch, frames in bank.typing.items():
            names = [n for n, _b in frames]
            self.assertNotIn(f"{ch}_type08" if ch != "usagi" else "none", names)
            self.assertGreaterEqual(len(names), 6)

    def test_03e_each_key_press_changes_the_hands_immediately(self):
        r = self.r
        r.step(3)
        for _ in range(8):
            before = {c: p.frame for c, p in r.m.pets.items()}
            r.step(0.5, dt=0.05)                                            # 자동 전환이 끼어들 틈 없이
            before = {c: p.frame for c, p in r.m.pets.items()}
            r.presses = 1                                                   # 키를 누른 순간
            r.m._react(r.mono.t)
            after = {c: p.frame for c, p in r.m.pets.items()}
            for c in CHARS:
                self.assertIn("_type", after[c])
                self.assertNotEqual(before[c], after[c], c)                 # 같은 틱에 손 모양이 바뀜
        r.idle = 120.0                                                      # 입력이 멈춘 뒤의 키 신호는 무시(쉬는 중)
        r.step(3)
        r.presses = 1
        r.m._react(r.mono.t)
        self.assertEqual(set(r.modes().values()), {"idle"})

    def test_03f_usagi_has_no_three_arm_frames(self):
        names = [n for n, _b in self.r.m.bank.typing["usagi"]]
        for bad in ("usagi_type04", "usagi_type05", "usagi_type06"):
            self.assertNotIn(bad, names)
        self.assertGreaterEqual(len(names), 5)

    def test_03g_head_items_never_move_while_characters_work_or_rest(self):
        r = self.r
        seen = {c: set() for c in CHARS}

        def probe():
            for c in CHARS:
                it = r.m.items[c]
                seen[c].add((it.x(), it.y(), r.m.pets[c].anchor_global().x(), r.m.pets[c].anchor_global().y()))
        r.step(2)
        r.step(25, each=probe)                                               # 일하는 동안
        r.idle = 120.0
        r.step(40, dt=0.1, each=probe)                                       # 쉬는 동안(다양한 동작)
        r.idle = 31 * 60.0
        r.step(5, each=probe)                                                # 차 마시는 동안
        for c in CHARS:
            self.assertEqual(len(seen[c]), 1, (c, seen[c]))                  # 위치가 한 번도 바뀌지 않음

    def test_03b_typing_does_not_move_the_body_or_desk(self):
        r = self.r
        r.step(3)
        for p in r.m.pets.values():
            self.assertEqual(p.mode, "type")
        seen = set()
        r.step(20, each=lambda: seen.update((c, p._motion) for c, p in r.m.pets.items()))
        self.assertTrue(all(m == (0.0, 0.0, 0.0) for _c, m in seen), seen)   # 책상이 포함된 그림이라 몸을 움직이지 않는다
        for it in r.m.items.values():
            self.assertFalse(hasattr(it, "_swing") and it._swing, "머리 위 물건이 흔들림")

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
        self.assertTrue(set(CHARS) <= set(v["carry"]))
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
        timer_item = r.m.item_of("clock")
        self.assertTrue(timer_item.alerting())                               # 30분 전: 퇴근 타이머가 색으로 알림
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
        self.assertIsInstance(r.m.items["usagi"], it_mod.ClockItem)          # 퇴근 타이머가 머리 위에
        self.assertFalse(hasattr(it_mod, "TimerItem"))                       # 집중 타이머는 없다
        r.m.set_carry("chiikawa", "clock")                                   # 퇴근 타이머는 한 마리만: 방금 고른 캐릭터가 갖고, 갖고 있던 usagi 는 포스트잇
        self.assertIsInstance(r.m.items["chiikawa"], it_mod.ClockItem)
        self.assertIsInstance(r.m.items["usagi"], pi_mod.PostIt)
        self.assertEqual(r.m.cfg["carry"]["usagi"], "memo")
        r.m.set_carry("usagi", "timer")                                      # 예전 설정값(timer)은 퇴근 타이머로 읽힘 → usagi 가 가져감
        self.assertIsInstance(r.m.items["usagi"], it_mod.ClockItem)
        self.assertIsInstance(r.m.items["chiikawa"], pi_mod.PostIt)
        r.m.set_carry("chiikawa", "clock")
        a = r.m.pets["chiikawa"].anchor_global()
        t = r.m.items["chiikawa"]
        self.assertLessEqual(t.geometry().top() + t.note_rect().bottom(), a.y())
        saved = mg.load_config(Path(r.tmp.name) / "config.json")
        self.assertEqual(saved["carry"]["chiikawa"], "clock")                # 설정이 저장됨

    def test_12_clock_item_open_close(self):
        r = self.r
        t = r.m.items["usagi"]
        self.assertFalse(t.is_open())
        t.open_full()
        self.assertTrue(t.is_open())
        r.step(1)
        self.assertIn("퇴근까지", t.sub_text if hasattr(t, "sub_text") else "퇴근까지")
        t.collapse()
        self.assertFalse(t.is_open())

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
        self.assertEqual((HERE / "panel.py").read_text(encoding="utf-8").count("COPYRIGHT_NOTICE"), 4)   # 정의 + 하단 라벨 + 표기 문구 만드는 곳(설정 창 안에서만)

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
            sizes, shown, wins = [], [], []
            for _ in range(40):                                              # 300ms = 약 9 프레임(33ms)
                r.mono.t += 0.033
                note.step_anim(r.mono.t)
                sizes.append(note.cur_size()[0])
                wins.append((note.width(), note.height()))
                shown.append(note.edit.isVisible())
                if not note.animating():
                    break
            self.assertFalse(note.animating())
            self.assertEqual(sizes, sorted(sizes))                           # 부드럽게 커짐
            self.assertGreater(note.width(), pill.width())
            self.assertEqual(len(set(wins[:-1])), 1, wins)                   # 도중에는 창 크기를 바꾸지 않는다(끊김 방지)
            self.assertTrue(shown[-1])
            self.assertFalse(shown[0])                                       # 82% 이후에 내용이 나타남
            n_frames = len(sizes)
            self.assertTrue(7 <= n_frames <= 12, n_frames)
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
        self.assertEqual([b.text() for b in note.fmt.values()], ["글꼴", "제목", "목록", "B", "I", "S", "링크"])
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
        # 저장 버튼은 없다(자동 저장) — Ctrl+S 로는 바로 저장
        self.assertNotIn("save", note.fmt)
        ed.setPlainText("저장 시험")
        self.assertFalse(note._saved)
        QTest.keyClick(ed, Qt.Key_S, Qt.ControlModifier)
        self.assertTrue(note._saved)
        # 오른쪽 클릭 메뉴: 선택한 글자만 글꼴 변경
        ed.setPlainText("가나다라마")
        select(1, 3)
        labels = [a.text() for a in ed.build_context_menu().actions()]
        self.assertIn("선택한 글자 글꼴…", labels)
        self.assertIn("선택한 글자 서식 지우기", labels)
        select(2, 2)
        self.assertNotIn("선택한 글자 글꼴…", [a.text() for a in ed.build_context_menu().actions()])
        select(1, 3)
        menu = ed.build_context_menu()
        next(a for a in menu.actions() if a.text() == "굵게").trigger()
        self.assertGreaterEqual(fmt_at(1).fontWeight(), 75)
        self.assertFalse(fmt_at(3).fontWeight() >= 75)
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

    def test_29_font_button_applies_to_selection_only_when_text_is_selected(self):
        from unittest import mock
        from PyQt5.QtGui import QFont
        note = self.r.m.items["chiikawa"]
        note.open_full()
        ed = note.edit
        ed.setPlainText("Hello World abc")
        c = ed.textCursor()
        c.setPosition(6)
        c.setPosition(11, QTextCursor.KeepAnchor)
        ed.setTextCursor(c)
        picked = QFont("DejaVu Serif")
        picked.setPointSizeF(16)
        picked.setBold(True)
        with mock.patch.object(pi_mod.QFontDialog, "getFont", return_value=(picked, True)):
            note.fmt["font"].click()                                          # 서식 줄의 글꼴 버튼(선택이 있으면 그 부분만)
        base = note.note["font_family"]
        self.assertEqual(base, "")                                            # 전체 글꼴은 바뀌지 않음
        probe = QTextCursor(ed.document())
        probe.setPosition(9)
        self.assertEqual(probe.charFormat().fontFamily(), "DejaVu Serif")
        for i in (1, 14):
            probe.setPosition(i)
            self.assertNotEqual(probe.charFormat().fontFamily(), "DejaVu Serif")
        note.flush_now()
        self.assertEqual(ns.NoteStore(Path(self.r.tmp.name) / "notes.json").for_owner("chiikawa")["font_family"], "")
        # 오른쪽 클릭 메뉴로도 같은 결과
        ed.setPlainText("가나다 라마바")
        c = ed.textCursor()
        c.setPosition(4)
        c.setPosition(7, QTextCursor.KeepAnchor)
        ed.setTextCursor(c)
        picked2 = QFont("DejaVu Sans Mono")
        picked2.setPointSizeF(14)
        with mock.patch.object(pi_mod.QFontDialog, "getFont", return_value=(picked2, True)):
            next(a for a in ed.build_context_menu().actions() if a.text() == "선택한 글자 글꼴…").trigger()
        for i, want in ((2, False), (6, True)):
            probe.setPosition(i)
            self.assertEqual(probe.charFormat().fontFamily() == "DejaVu Sans Mono", want, i)

    def test_30_clockout_time_typed_with_keyboard_and_red_when_near(self):
        r = self.r
        d = panel_mod.SettingsDialog(r.m.cfg, bank=r.m.bank, scales={c: p.scale for c, p in r.m.pets.items()})
        d.show()
        d.co_time.selectAll()
        QTest.keyClicks(d.co_time, "1745")                                     # 키보드로 바로 입력
        d.co_time.editingFinished.emit()
        self.assertEqual(d.values()["clockout"]["time"], "17:45")
        d.co_time.setText("99:99")                                             # 잘못 쓰면 이전 값 유지
        d.co_time.editingFinished.emit()
        self.assertEqual(d.values()["clockout"]["time"], "17:45")
        d.red_min.setValue(15)
        self.assertEqual(d.values()["clockout"]["warn"], [35, 15])
        d.close()
        r.m.apply_settings({**d.values(), "enabled": list(CHARS), "on_top": True, "autostart": False,
                            "follow": r.m.cfg["follow"]})
        clock = r.m.item_of("clock")
        r.now = datetime(2026, 11, 18, 17, 20)                                 # 퇴근 25분 전: 주황
        r.step(1)
        self.assertEqual(clock._big_color(), "#D98324")
        r.now = datetime(2026, 11, 18, 17, 31)                                 # 14분 전: 빨강
        r.step(1)
        self.assertEqual(clock._big_color(), "#E5484D")
        self.assertEqual(clock.phase, "warn10")

    def test_31_note_list_plus_button_and_multiple_notes(self):
        from unittest import mock
        r = self.r
        note = r.m.items["chiikawa"]
        note.open_full()
        self.assertEqual(list(note.buttons()), ["collapse", "list", "add", "color"])     # ×(지우기) 대신 목록·＋
        rects = list(note.buttons().values())
        for i, a in enumerate(rects):
            self.assertTrue(note.note_rect().contains(a))
            for b in rects[i + 1:]:
                self.assertFalse(a.intersects(b))
        self.assertGreater(note._title_rect(note.note_rect()).width(), 30)
        note.edit.setPlainText("첫 번째 메모\n☐ 할 일")
        first_id = note.note["id"]
        note.button_clicked("add")                                                       # ＋
        self.assertNotEqual(note.note["id"], first_id)
        self.assertEqual(note.edit.toPlainText(), "")                                    # 새 포스트잇은 빈 장
        self.assertEqual(len(r.m.store.notes_of("chiikawa")), 2)
        self.assertNotEqual(note.note["color"], r.m.store.get(first_id)["color"])        # 색이 다름
        note.edit.setPlainText("두 번째 메모")
        note.flush_now()
        self.assertEqual(r.m.store.get(first_id)["text"], "첫 번째 메모\n☐ 할 일")          # 첫 장은 그대로
        labels = [a.text() for a in note.note_list_menu().actions() if a.text()]
        self.assertTrue(any("첫 번째 메모" in x for x in labels), labels)
        self.assertTrue(any("두 번째 메모" in x for x in labels), labels)
        self.assertIn("＋ 새 포스트잇", labels)
        next(a for a in note.note_list_menu().actions() if "첫 번째 메모" in a.text()).trigger()   # 목록에서 고르기
        self.assertEqual(note.note["id"], first_id)
        self.assertEqual(note.edit.toPlainText(), "첫 번째 메모\n☐ 할 일")
        self.assertEqual(note.progress(), (0, 1))
        again = ns.NoteStore(Path(r.tmp.name) / "notes.json")                            # 다시 켜도 들고 있던 장
        self.assertEqual(again.for_owner("chiikawa")["id"], first_id)
        self.assertEqual(len(again.notes_of("chiikawa")), 2)
        with mock.patch("PyQt5.QtWidgets.QMessageBox.question", return_value=16384):     # 삭제(확인)
            note.confirm_delete()
        self.assertEqual(len(r.m.store.notes_of("chiikawa")), 1)
        self.assertEqual(note.edit.toPlainText(), "두 번째 메모")                         # 남은 장을 듦(글이 섞이지 않음)
        note.edit.setPlainText("")
        note.confirm_delete()                                                            # 하나뿐인 빈 장을 지우면 새 빈 장
        self.assertEqual(len(r.m.store.notes_of("chiikawa")), 1)
        self.assertEqual(note.edit.toPlainText(), "")
        for _ in range(ns.MAX_PER_OWNER + 3):
            note.new_note()
        self.assertEqual(len(r.m.store.notes_of("chiikawa")), ns.MAX_PER_OWNER)

    def test_32_choose_which_characters_appear(self):
        r = self.r
        self.assertTrue(r.m.set_character("hachiware", False))
        self.assertEqual(set(r.m.pets), {"chiikawa", "usagi"})
        self.assertNotIn("hachiware", r.m.items)                            # 머리 위 물건도 함께 사라짐
        self.assertTrue(r.m.set_character("chiikawa", False))
        self.assertFalse(r.m.set_character("usagi", False))                  # 마지막 한 마리는 남는다
        self.assertEqual(set(r.m.pets), {"usagi"})
        self.assertEqual(r.m.cfg["leader"], "usagi")
        saved = mg.load_config(Path(r.tmp.name) / "config.json")
        self.assertEqual(saved["enabled"], ["usagi"])                        # 저장됨(다시 켜도 유지)
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"type"})
        self.assertTrue(r.m.set_character("hachiware", True))                # 다시 나타남 + 원래 들던 포스트잇
        self.assertIsInstance(r.m.items["hachiware"], pi_mod.PostIt)
        self.assertTrue(r.m.set_character("chiikawa", True))
        self.assertIsInstance(r.m.items["chiikawa"], pi_mod.PostIt)
        r.step(2)
        self.assertEqual(set(r.modes().values()), {"type"})
        menu = __import__("PyQt5.QtWidgets", fromlist=["QMenu"]).QMenu()
        cm = r.m.add_character_menu(menu)
        self.assertEqual([a.text() for a in cm.actions()], ["치이카와", "하치와레", "우사기"])
        self.assertTrue(all(a.isChecked() for a in cm.actions()))

    def test_33_settings_shows_keyboard_detection_status(self):
        r = self.r
        d = panel_mod.SettingsDialog(r.m.cfg, bank=r.m.bank, scales={c: p.scale for c, p in r.m.pets.items()})
        d.show()
        d._refresh_follow_status()
        text = d.follow_status.text()
        self.assertIn("빌드", text)
        self.assertTrue("확인" in text)                                      # 리눅스 시험 환경에선 '확인할 수 없어요' 문구
        d.close()

    def test_34_clock_shows_reason_instead_of_dashes_and_skip_can_be_undone(self):
        r = self.r
        clock = r.m.item_of("clock")
        r.now = datetime(2026, 11, 21, 12, 0)                                  # 토요일
        r.step(1)
        self.assertEqual(clock.big, "휴일")
        self.assertNotEqual(clock.big, "--")
        r.now = datetime(2026, 11, 18, 12, 0)
        r.step(1)
        self.assertEqual(clock.phase, "far")
        r.m._skip_today()
        r.step(1)
        self.assertEqual(clock.big, "끔")
        self.assertEqual(clock.b_skip.text(), "다시 켜기")
        r.m._skip_today()                                                      # 한 번 더 누르면 되돌림
        r.step(1)
        self.assertEqual(clock.phase, "far")
        self.assertEqual(clock.b_skip.text(), "오늘은 끄기")
        r.m._skip_today()
        r.m.apply_settings({"enabled": list(CHARS), "on_top": True, "autostart": False, "carry": r.m.cfg["carry"],
                            "follow": r.m.cfg["follow"], "scales": {},
                            "clockout": {"enabled": True, "time": "17:00", "days": [0, 1, 2, 3, 4], "warn": [30, 10]}})
        r.step(1)
        self.assertEqual(r.m.cfg["clockout"]["skip_date"], "")                 # 설정을 다시 정하면 풀림
        clock = r.m.item_of("clock")                                           # 설정을 적용하면 물건이 새로 만들어진다
        self.assertEqual(clock.phase, "far")
        r.m.cfg["clockout"]["enabled"] = False
        r.step(1)
        self.assertEqual(r.m.item_of("clock").big, "꺼짐")

    def test_45_slide_down_the_chair_when_clock_out_is_near(self):
        r = self.r
        r.step(3)
        pets = list(r.m.pets.values())
        self.assertTrue(all(p.slide_fraction(r.mono.t) == 0.0 for p in pets))     # 평소엔 앉은 자리 그대로
        r.now = datetime(2026, 11, 18, 17, 25)                                    # 퇴근 35분 전(아직 임박 아님)
        r.step(2)
        self.assertFalse(any(p._hurry for p in pets))
        r.now = datetime(2026, 11, 18, 17, 52)                                    # 퇴근 8분 전 → 미끄러지기 시작
        r.step(1)
        self.assertTrue(all(p._hurry for p in pets))
        series = {c: [] for c in r.m.pets}
        seen_items = {c: set() for c in r.m.pets}

        def probe():
            for c, p in r.m.pets.items():
                series[c].append(p._slide)
                seen_items[c].add((r.m.items[c].x(), r.m.items[c].y()))
        r.step(30, dt=0.1, each=probe)
        for c, v in series.items():
            self.assertGreaterEqual(max(v), 0.99, c)                              # 끝까지 내려가고
            self.assertEqual(min(v), 0.0, c)                                      # 다시 올라온다
            self.assertTrue(all(abs(b - a) < 0.2 for a, b in zip(v, v[1:])), c)   # 뚝뚝 끊기지 않고 부드럽게
            self.assertEqual(len(seen_items[c]), 1, c)                            # 머리 위 물건은 그대로
        starts = {round(p._slide_off, 1) for p in pets}
        self.assertEqual(len(starts), 3)                                          # 마리마다 시작 시각이 다름
        # 그림: 책상(아래쪽)은 그대로, 몸(위쪽)만 내려간다
        pet = r.m.pets["chiikawa"]
        pet.show()
        r.step(2)
        self.assertEqual(pet.mode, "type")
        top = r.m.bank.desk_top(pet.frame)
        self.assertIsNotNone(top)
        pet._slide = 0.0
        base = pet.grab().toImage()
        pet._slide = 1.0
        slid = pet.grab().toImage()
        line = int(pet._geom()[3] + top * pet.scale) + 2
        lower_same = all(base.pixel(x, y) == slid.pixel(x, y) for y in range(line, base.height(), 3) for x in range(0, base.width(), 3))
        upper_diff = any(base.pixel(x, y) != slid.pixel(x, y) for y in range(0, line - 2, 2) for x in range(0, base.width(), 2))
        self.assertTrue(lower_same, "책상이 움직임")
        self.assertTrue(upper_diff, "몸이 내려가지 않음")
        # 키를 안 치거나 쉬는 중이어도(모든 캐릭터) 퇴근 임박이면 자리에 앉아 미끄러진다 — 손 모양은 그대로
        r.idle = 120.0
        r.step(3)
        self.assertEqual(set(r.modes().values()), {"type"})
        frames = {c: set() for c in r.m.pets}
        slid = {c: 0.0 for c in r.m.pets}

        def probe2():
            for c, p in r.m.pets.items():
                frames[c].add(p.frame)
                slid[c] = max(slid[c], p._slide)
        r.step(12, dt=0.1, each=probe2)
        for c in frames:
            self.assertEqual(len(frames[c]), 1, (c, frames[c]))                   # 키를 안 치면 손 모양이 바뀌지 않음
            self.assertGreaterEqual(slid[c], 0.99, c)                              # 그래도 모두 미끄러진다
        r.presses = 1
        r.idle = 0.2
        r.step(0.4, dt=0.05)
        self.assertEqual(set(r.modes().values()), {"type"})
        r.idle = 120.0
        # 색 알림(주황·빨강)을 꺼 두어도 퇴근 10분 안이면 미끄러진다
        r.m.cfg["clockout"]["warn"] = []
        r.now = datetime(2026, 11, 18, 17, 55)
        r.step(1)
        self.assertTrue(all(p._hurry for p in pets))
        r.now = datetime(2026, 11, 18, 17, 20)
        r.step(1)
        self.assertFalse(any(p._hurry for p in pets))
        # 우클릭 '미리보기': 시간과 상관없이 20초 동안
        r.m.preview_hurry()
        r.step(1)
        self.assertTrue(all(p._hurry for p in pets))
        r.step(25)
        self.assertFalse(any(p._hurry for p in pets))
        menu = __import__("PyQt5.QtWidgets", fromlist=["QMenu"]).QMenu()
        r.m.add_character_menu(menu)
        r.now = datetime(2026, 11, 18, 18, 10)                                    # 퇴근 시간이 지나면 멈춘다
        r.step(3)
        self.assertFalse(any(p._hurry for p in pets))

    def test_28_postit_can_be_resized_by_dragging_the_corner(self):
        from PyQt5.QtCore import QEvent, QPoint, QPointF
        from PyQt5.QtGui import QMouseEvent
        r = self.r
        note = r.m.items["chiikawa"]
        note.open_full()
        w0, h0 = note.open_size()
        g = note.grip_rect().center().toPoint()
        origin = QPoint(500, 400)

        def ev(kind, pos, buttons):
            return QMouseEvent(kind, QPointF(pos), QPointF(origin + (pos - g)), Qt.LeftButton, buttons, Qt.NoModifier)
        note.mousePressEvent(ev(QEvent.MouseButtonPress, g, Qt.LeftButton))
        note.mouseMoveEvent(ev(QEvent.MouseMove, g + QPoint(-30, -40), Qt.LeftButton))
        self.assertEqual(note.open_size(), (w0 + 60, h0 + 40))                 # 왼쪽 위로 끌면 커진다(옆은 좌우 대칭)
        a = r.m.pets["chiikawa"].anchor_global()
        self.assertLessEqual(note.geometry().top() + note.note_rect().bottom(), a.y())    # 머리 위에 그대로
        note.mouseMoveEvent(ev(QEvent.MouseMove, g + QPoint(500, 500), Qt.LeftButton))
        self.assertEqual(note.open_size(), (float(ns.MIN_W), float(ns.MIN_H)))   # 최소 크기 제한
        note.mouseMoveEvent(ev(QEvent.MouseMove, g + QPoint(-400, -400), Qt.LeftButton))
        self.assertEqual(note.open_size(), (float(ns.MAX_W), float(ns.MAX_H)))   # 최대 크기 제한
        note.mouseMoveEvent(ev(QEvent.MouseMove, g + QPoint(-20, -10), Qt.LeftButton))
        note.mouseReleaseEvent(ev(QEvent.MouseButtonRelease, g, Qt.NoButton))
        saved = ns.NoteStore(Path(r.tmp.name) / "notes.json").for_owner("chiikawa")
        self.assertEqual((saved["width"], saved["height"]), (int(w0 + 40), int(h0 + 10)))   # 놓으면 저장
        self.assertTrue(note.is_open())                                        # 크기를 조절해도 접히지 않는다

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

    # ── 포차코(내 PC의 팩에서 불러오는 선택 캐릭터) ──────────────────────────
    def test_40_pochacco_needs_a_local_pack(self):
        r = Rig(enabled=CHARS + ("pochacco",))                              # 팩이 없으면 목록에 있어도 나오지 않는다
        try:
            self.assertEqual(set(r.m.pets), set(CHARS))
            self.assertFalse(r.m.set_pochacco_count(2))
            menu = __import__("PyQt5.QtWidgets", fromlist=["QMenu"]).QMenu()
            cm = r.m.add_character_menu(menu)
            self.assertEqual([a.text() for a in cm.actions()], ["치이카와", "하치와레", "우사기"])
            d = panel_mod.SettingsDialog(r.m.cfg, bank=r.m.bank, scales={c: p.scale for c, p in r.m.pets.items()})
            self.assertFalse(d.poch_ready)
            self.assertEqual(d.ids, list(CHARS))
            self.assertEqual(d.values()["enabled"], list(CHARS))
            self.assertEqual(d._credit_text(), panel_mod.COPYRIGHT_NOTICE)
            d.close()
        finally:
            r.close()

    def test_41_several_pochaccos_do_different_actions_and_stay_in_their_roles(self):
        r = Rig(enabled=CHARS + POCHACCO_IDS[:3], pack=True)
        try:
            self.assertEqual(len(r.m.pets), 6)
            r.step(3)
            self.assertEqual(set(r.modes().values()), {"type"})              # 함께 일할 땐 모두 두드림
            for c in POCHACCO_IDS[:3]:
                self.assertTrue(r.m.pets[c].frame.startswith("pochacco_type"), r.m.pets[c].frame)
            frames = {c: [] for c in POCHACCO_IDS[:3]}
            r.step(20, each=lambda: [frames[c].append(r.m.pets[c].frame) for c in frames])
            self.assertEqual(len({tuple(v) for v in frames.values()}), 3)    # 손 모양 순서가 마리마다 다름
            r.idle = 120.0                                                   # 쉬는 동작
            r.step(3)
            dups, seen = [], {c: [] for c in r.m.pets}
            typed = []

            def probe():
                names = {c: p.action_name() for c, p in r.m.pets.items()}
                act = [n for n in names.values() if n]
                if len(act) != len(set(act)):
                    dups.append(names)
                for c, n in names.items():
                    if n and (not seen[c] or seen[c][-1] != n):
                        seen[c].append(n)
                typed.extend(c for c, p in r.m.pets.items() if "_type" in p.frame)
            r.step(240, each=probe)
            self.assertEqual(dups, [], dups[:1])                             # 같은 순간에 같은 동작 없음(포차코끼리도)
            self.assertEqual(typed, [])                                      # 쉬는 중엔 키보드 컷 없음
            for c in POCHACCO_IDS[:3]:
                self.assertGreaterEqual(len(set(seen[c])), 6, (c, seen[c]))  # 다양한 동작
                for a, b in zip(seen[c], seen[c][1:]):
                    self.assertNotEqual(a, b)                                # 연달아 같은 동작 없음
            r.idle = 31 * 60.0                                               # 30분 입력 없음 → 모두 차 마시기(컷 천천히 바뀜)
            r.step(3)
            self.assertEqual(set(r.modes().values()), {"rest"})
            teas = set()
            r.step(40, each=lambda: teas.add(r.m.pets["pochacco"].frame))
            self.assertGreaterEqual(len(teas), 2, teas)
            r.idle = 0.5
            r.step(0.4, dt=0.05)
            self.assertEqual(set(r.modes().values()), {"type"})              # 키를 누르면 바로 돌아옴
        finally:
            r.close()

    def test_42_pochacco_count_items_and_separate_settings(self):
        from unittest import mock
        r = Rig(pack=True)
        try:
            self.assertEqual(r.m.pochacco_count(), 0)
            self.assertTrue(r.m.set_pochacco_count(3))
            self.assertEqual([c for c in POCHACCO_IDS if c in r.m.pets], list(POCHACCO_IDS[:3]))
            for c in POCHACCO_IDS[:3]:
                self.assertIsInstance(r.m.items[c], pi_mod.PostIt)           # 마리마다 자기 포스트잇
            ids = {r.m.items[c].note["id"] for c in POCHACCO_IDS[:3]}
            self.assertEqual(len(ids), 3)
            self.assertTrue(r.m.set_pochacco_count(1))
            self.assertEqual(r.m.pochacco_count(), 1)
            saved = mg.load_config(Path(r.tmp.name) / "config.json")
            self.assertIn("pochacco", saved["enabled"])
            self.assertNotIn("pochacco2", saved["enabled"])
            # 설정 창: 먹작귀와 따로
            d = panel_mod.SettingsDialog(r.m.cfg, bank=r.m.bank, scales={c: p.scale for c, p in r.m.pets.items()})
            d.show()
            self.assertTrue(d.poch_ready)
            self.assertTrue(d.poch_on.isChecked())
            self.assertEqual(d.poch_count.value(), 1)
            self.assertIn("SANRIO", d._credit_text())
            self.assertIn(panel_mod.COPYRIGHT_NOTICE, d._credit_text())
            texts = [c.text() for c in d.findChildren(__import__('PyQt5.QtWidgets', fromlist=['QCheckBox']).QCheckBox)]
            self.assertIn("포차코", texts)                                       # 다른 캐릭터와 같은 목록에서 고른다
            self.assertNotIn("포차코도 나오게 하기", texts)
            self.assertEqual([c for c in texts if c in ("치이카와", "하치와레", "우사기", "포차코")], ["치이카와", "하치와레", "우사기", "포차코"])
            d.poch_count.setValue(3)
            self.assertEqual([c for c in d.values()["enabled"] if c.startswith("pochacco")], list(POCHACCO_IDS[:3]))
            self.assertTrue(d.slider_rows["pochacco3"].isVisibleTo(d))
            self.assertFalse(d.slider_rows["pochacco4"].isVisibleTo(d))
            d.poch_on.setChecked(False)
            self.assertEqual([c for c in d.values()["enabled"] if c.startswith("pochacco")], [])
            self.assertEqual(d._credit_text(), panel_mod.COPYRIGHT_NOTICE)    # 포차코가 없으면 산리오 표기도 없다
            d.close()
            menu = __import__("PyQt5.QtWidgets", fromlist=["QMenu"]).QMenu()
            cm = r.m.add_character_menu(menu)
            sub = next(a for a in cm.actions() if a.menu() is not None and "포차코" in a.text()).menu()
            self.assertEqual([a.text() for a in sub.actions()], ["나오지 않음", "1마리", "2마리", "3마리", "4마리"])
            sub.actions()[2].trigger()
            self.assertEqual(r.m.pochacco_count(), 2)
            # 퇴근 타이머는 한 마리만
            r.m.set_carry("pochacco", "clock")                               # 우사기가 이미 들고 있어도 방금 고른 포차코가 갖는다
            self.assertIsInstance(r.m.items["pochacco"], it_mod.ClockItem)
            self.assertIsInstance(r.m.items["usagi"], pi_mod.PostIt)
            kinds = [type(it).__name__ for it in r.m.items.values()]
            self.assertEqual(kinds.count("ClockItem"), 1)                    # 전체에서 한 마리만
            r.m.set_carry("pochacco2", "clock")
            self.assertIsInstance(r.m.items["pochacco2"], it_mod.ClockItem)
            self.assertIsInstance(r.m.items["pochacco"], pi_mod.PostIt)
            # 설정 창에서도 같다: 포차코에 퇴근 타이머를 고르면 우사기의 것은 포스트잇으로
            d2 = panel_mod.SettingsDialog(r.m.cfg, bank=r.m.bank, scales={c: p.scale for c, p in r.m.pets.items()})
            d2.carry_cb["usagi"].setCurrentIndex(d2.carry_cb["usagi"].findData("clock"))
            d2.carry_cb["pochacco"].setCurrentIndex(d2.carry_cb["pochacco"].findData("clock"))
            self.assertEqual(d2.carry_cb["usagi"].currentData(), "memo")
            v2 = d2.values()
            self.assertEqual([c for c, k in v2["carry"].items() if k == "clock" and c in v2["enabled"]], ["pochacco"])
            d2.close()
        finally:
            r.close()

    def test_44_several_pochaccos_are_placed_side_by_side(self):
        r = Rig(enabled=POCHACCO_IDS, pack=True)
        try:
            xs = [r.m.pets[c].x() for c in POCHACCO_IDS]
            self.assertEqual(len(set(xs)), 4, xs)                            # 겹치지 않고 한 줄로
            r2 = r.m.set_pochacco_count(2)
            r.m.set_pochacco_count(4)
            self.assertEqual(len({r.m.pets[c].x() for c in POCHACCO_IDS}), 4)
        finally:
            r.close()

    def test_43_pochacco_typing_uses_no_angled_frames_and_keeps_head_items_still(self):
        r = Rig(enabled=("pochacco", "pochacco2"), pack=True)
        try:
            names = [n for n, _b in r.m.bank.typing["pochacco"]]
            self.assertEqual(len(names), 6)
            seen = {c: set() for c in r.m.pets}
            r.step(2)
            r.step(30, each=lambda: [seen[c].add((r.m.items[c].x(), r.m.items[c].y())) for c in seen])
            r.idle = 120.0
            r.step(60, dt=0.1, each=lambda: [seen[c].add((r.m.items[c].x(), r.m.items[c].y())) for c in seen])
            for c in seen:
                self.assertEqual(len(seen[c]), 1, (c, seen[c]))              # 머리 위 물건이 움직이지 않음
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
