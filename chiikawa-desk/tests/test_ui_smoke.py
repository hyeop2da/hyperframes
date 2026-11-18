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

from PyQt5.QtCore import QPoint, QTimer, Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

import idle_probe
import manager as mg
import notes_store as ns
import timer_engine as te
import work_reactor as wr
from pet import PoseBank

APP = QApplication.instance() or QApplication(sys.argv)
QTimer.singleShot = staticmethod(lambda ms, fn: fn())      # 시차 합류 등을 즉시 실행(시험용)
SHOTS = os.environ.get("SHOTS_DIR")


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
    def __init__(self, enabled=("chiikawa", "hachiware", "usagi")):
        self.tmp = tempfile.TemporaryDirectory()
        self.mono, self.wall = Clock(1000.0), Clock(2_000_000.0)
        self.probe = FakeProbe(self.mono)
        self.now = datetime(2026, 11, 18, 14, 0)
        cfg = mg.load_config(Path(self.tmp.name) / "config.json", reset=True)
        cfg["enabled"] = list(enabled)
        self.store = ns.NoteStore(Path(self.tmp.name) / "notes.json")
        self.m = mg.PetManager(cfg, Path(self.tmp.name) / "config.json", self.store, PoseBank(HERE / "frames" / "poses"),
                               self.probe, reactor=wr.WorkReactor(), mono=self.mono, wall=self.wall,
                               now_fn=lambda: self.now)

    def step(self, secs, typing=False, kps=5.0, dt=0.25):
        end = self.mono.t + secs
        while self.mono.t < end:
            self.mono.t += dt
            self.wall.t += dt
            if typing:
                self.probe.last_input = int(self.mono.t * kps) / kps
            self.m._poll()
            self.m._motion()

    def poses(self):
        return {c: p.pose for c, p in self.m.pets.items()}

    def intens(self):
        return {c: round(p.intensity, 2) for c, p in self.m.pets.items()}

    def close(self):
        self.m.quit_app = lambda: None
        for w in list(self.m.pets.values()) + list(self.m.notes.values()) + [self.m.card, self.m.chip]:
            w.close()
        self.tmp.cleanup()


class UiSmoke(unittest.TestCase):
    def setUp(self):
        self.r = Rig()

    def tearDown(self):
        self.r.close()

    def test_01_typing_makes_leader_focus_then_friends_join(self):
        r = self.r
        self.assertEqual(set(r.poses().values()), {"base"})
        r.step(6, typing=True)
        self.assertEqual(r.m.pets["chiikawa"].pose, "focus")                 # ① 대표가 집중 포즈로
        self.assertEqual(r.m.pets["hachiware"].pose, "base")                 #   친구들은 아직
        r.step(36, typing=True)
        self.assertEqual(set(r.poses().values()), {"focus"})                 # ② 나머지도 함께
        self.assertGreater(r.m.pets["chiikawa"].intensity, 0.9)

    def test_02_pause_decays_then_resumes(self):
        r = self.r
        r.step(40, typing=True)
        r.step(8)                                                            # 입력을 멈춤 → 움직임이 잦아듦
        self.assertEqual(set(r.poses().values()), {"focus"})
        self.assertLess(r.m.pets["chiikawa"].intensity, 0.6)
        r.step(20)
        self.assertLess(r.m.pets["chiikawa"].intensity, 0.05)
        r.step(30)                                                           # 45초 넘게 무활동 → 기본
        self.assertEqual(set(r.poses().values()), {"base"})
        r.step(4, typing=True)                                               # ③ 재개 → 다시 움직임
        self.assertEqual(r.m.pets["chiikawa"].pose, "focus")
        self.assertGreater(r.m.pets["chiikawa"].intensity, 0.3)

    def test_03_rest_timer_beats_typing_and_input_never_controls_timer(self):
        r = self.r
        r.step(10, typing=True)
        self.assertEqual(r.m.timer.status, te.IDLE)                          # 입력만으로 타이머가 시작되지 않음
        r.m._primary()                                                       # 집중 시작
        self.assertEqual((r.m.timer.phase, r.m.timer.status), (te.FOCUS, te.RUNNING))
        r.wall.t += 26 * 60
        r.step(1, typing=True)                                               # 집중 완료 → 응원
        self.assertEqual(r.m.timer.status, te.DONE)
        self.assertEqual(set(r.poses().values()), {"cheer"})
        r.m._primary()                                                       # 휴식 시작
        r.step(30, typing=True)                                              # ④ 타이핑해도 휴식 포즈 유지
        self.assertEqual((r.m.timer.phase, r.m.timer.status), (te.REST, te.RUNNING))
        self.assertEqual(set(r.poses().values()), {"rest"})
        self.assertEqual(set(r.intens().values()), {0.0})
        r.m._primary()                                                       # 일시정지해도 휴식 포즈
        self.assertEqual(set(r.poses().values()), {"rest"})

    def test_04_focus_timer_keeps_pose_when_idle(self):
        r = self.r
        r.m._primary()
        r.step(60)                                                           # 입력 없음: 집중 포즈 유지, 움직임만 약하게
        self.assertEqual(set(r.poses().values()), {"focus"})
        self.assertAlmostEqual(r.m.pets["hachiware"].intensity, 0.12, places=2)
        r.m._primary()                                                       # 일시정지 → 휴식 포즈
        self.assertEqual(set(r.poses().values()), {"rest"})
        r.m._primary()
        self.assertEqual(set(r.poses().values()), {"focus"})

    def test_05_reaction_switch_off_stops_motion(self):
        r = self.r
        r.step(10, typing=True)
        self.assertEqual(r.m.pets["chiikawa"].pose, "focus")
        v = {"focus_min": 25, "rest_min": 5, "react": False, "enabled": list(r.m.cfg["enabled"]),
             "leader": "chiikawa", "on_top": True, "clockout": dict(r.m.cfg["clockout"])}
        r.m.apply_settings(v)
        r.step(20, typing=True)                                              # ⑤ 반응을 끄면 입력에 따른 움직임 없음
        self.assertEqual(set(r.poses().values()), {"base"})
        self.assertEqual(set(r.intens().values()), {0.0})

    def test_06_unsupported_probe_keeps_everything_else_working(self):
        r = self.r
        r.m.probe = idle_probe.NullProbe("테스트용 미지원")
        r.step(10, typing=True)
        self.assertEqual(set(r.poses().values()), {"base"})
        r.m._primary()
        self.assertEqual(set(r.poses().values()), {"focus"})                 # 타이머·캐릭터는 그대로 동작

    def test_07_postit_open_close_checklist_and_persistence(self):
        r = self.r
        note = r.m.notes["chiikawa"]
        pet = r.m.pets["chiikawa"]
        self.assertFalse(note.is_open())
        pet.show()
        note.show()
        # 머리 위: 쪽지 아래 중앙이 머리 꼭대기 기준점 근처
        a = pet.anchor_global()
        g = note.geometry()
        self.assertLess(abs((g.left() + note.note_rect().center().x()) - a.x()), 4)
        self.assertLessEqual(g.top() + note.note_rect().bottom(), a.y())
        mini_size = note.size()
        note.open_full()                                                     # 펼치기
        self.assertTrue(note.is_open())
        self.assertGreater(note.width(), mini_size.width())
        done = []
        note.task_completed.connect(lambda _i: done.append(1))
        note.edit.setPlainText("주간 회의 준비\n")
        cur = note.edit.textCursor()
        cur.movePosition(cur.End)
        note.edit.setTextCursor(cur)
        QTest.keyClick(note.edit, Qt.Key_Return, Qt.ControlModifier)         # Ctrl+Enter → 체크리스트
        note.edit.insertPlainText("자료 정리")
        QTest.keyClick(note.edit, Qt.Key_Return, Qt.ControlModifier)
        note.edit.insertPlainText("발표 연습")
        self.assertEqual(note.note["text"], "주간 회의 준비\n☐ 자료 정리\n☐ 발표 연습")
        self.assertEqual(note.progress(), (0, 2))
        c2 = note.edit.textCursor()
        c2.setPosition(note.edit.document().findBlockByLineNumber(1).position())
        note.edit.toggle_box_at(c2)                                          # 눌러서 완료
        self.assertEqual(note.progress(), (1, 2))
        self.assertEqual(done, [1])
        self.assertEqual(r.m.pets["chiikawa"].pose, "cheer")                 # 완료하면 캐릭터가 기뻐함
        note.collapse()                                                      # 접기
        self.assertFalse(note.is_open())
        note.flush_now()
        again = ns.NoteStore(Path(r.tmp.name) / "notes.json")                # 저장 확인
        self.assertEqual(again.for_owner("chiikawa")["text"], "주간 회의 준비\n☑ 자료 정리\n☐ 발표 연습")

    def test_08_clockout_alert_and_badge(self):
        r = self.r
        r.now = datetime(2026, 11, 18, 17, 40)
        r.step(1)
        self.assertTrue(r.m.notes["chiikawa"].alerting())                    # 30분 전 쪽지가 흔들림
        r.now = datetime(2026, 11, 18, 18, 0)
        r.step(1)
        self.assertEqual(r.m.notes["usagi"]._badge, "퇴근!")
        self.assertEqual(set(r.poses().values()), {"cheer"})
        r.now = datetime(2026, 11, 21, 17, 55)                               # 토요일: 표시 없음
        r.step(1)
        self.assertEqual(r.m.notes["usagi"]._badge, "")

    def test_09_no_speech_bubble_code(self):
        for f in HERE.glob("*.py"):
            src = f.read_text(encoding="utf-8")
            self.assertNotIn("class Bubble", src, f.name)
            self.assertNotIn("class Toast", src, f.name)

    def test_10_tiny_size(self):
        pet = self.r.m.pets["usagi"]
        self.r.m.set_pet_scale(pet, 0.01)
        self.assertAlmostEqual(pet.scale, 0.08)
        self.assertLess(pet.width(), 40)
        self.assertLess(self.r.m.notes["usagi"].mscale, 0.7)


if __name__ == "__main__":
    unittest.main(verbosity=2)
