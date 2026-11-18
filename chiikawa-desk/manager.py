"""전체 조립: 여러 캐릭터 · 머리 위 포스트잇 · 집중 타이머 · 퇴근 시각 · 내 작업에 반응하기.

포즈 결정 우선순위(위가 먼저). 입력 활동은 타이머를 시작/정지하지 않는다.
  1) 휴식 타이머(진행·일시정지)  → 휴식 포즈 고정(입력이 있어도 움직임 없음)
  2) 집중 완료                   → 응원 포즈(휴식 시작 버튼을 누를 때까지)
  3) 응원 이벤트(버튼·자동 응원·할 일 완료·퇴근 정각) → 잠깐 응원 후 복귀
  4) 집중 타이머 일시정지         → 휴식 포즈
  5) 집중 타이머 진행 중          → 집중 포즈(움직임 강도는 작업량에 따름, 무활동이면 잦아듦)
  6) 타이머 없음                  → 작업 중(대표 먼저, 친구들은 시차를 두고)이면 집중, 아니면 기본
"""
import json
import math
import random
import time
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, QPoint, QTimer
from PyQt5.QtGui import QCursor, QIcon
from PyQt5.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import clock_out as co
import timer_engine as te
import work_reactor as wr
from notes_store import NoteStore
from panel import Chip, SettingsDialog, TimerCard
from pet import CHAR_LABEL, CHARS, SCALE_MAX, SCALE_MIN, SIZE_PRESETS, Pet
from postit import PostIt

STARTER_TEXT = "할 일\n" + "☐ "

DEFAULT_CONFIG = {
    "enabled": list(CHARS),
    "leader": "chiikawa",
    "react": True,
    "on_top": True,
    "opacity": 0.85,
    "focus_min": 25,
    "rest_min": 5,
    "clockout": {"enabled": True, "time": "18:00", "days": [0, 1, 2, 3, 4], "warn": [30, 10], "skip_date": ""},
    "pets": {ch: {"x": None, "y": None, "scale": 0.5} for ch in CHARS},
    "timer": {},
}


def load_config(path, reset=False):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if not reset and Path(path).exists():
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            for k, v in data.items():
                if k in cfg:
                    if isinstance(cfg[k], dict) and isinstance(v, dict):
                        cfg[k].update(v)
                    else:
                        cfg[k] = v
            for ch in CHARS:
                cfg["pets"].setdefault(ch, {"x": None, "y": None, "scale": 0.5})
        except (OSError, ValueError):
            pass
    cfg["enabled"] = [c for c in cfg["enabled"] if c in CHARS] or [CHARS[0]]
    if cfg["leader"] not in cfg["enabled"]:
        cfg["leader"] = cfg["enabled"][0]
    return cfg


def mini_scale_for(pet_scale):
    """캐릭터가 작을수록 머리 위 쪽지도 작게."""
    return max(0.6, min(1.25, 0.55 + 0.9 * pet_scale))


class PetManager(QObject):
    def __init__(self, cfg, cfg_path, store, bank, probe, reactor=None, timer=None,
                 mono=time.monotonic, wall=time.time, now_fn=datetime.now, debug=False):
        super().__init__()
        self.cfg, self.cfg_path, self.store, self.bank, self.probe = cfg, Path(cfg_path), store, bank, probe
        self.mono, self.now_fn, self.debug = mono, now_fn, debug
        self.reactor = reactor or wr.WorkReactor()
        self.timer = timer or te.PomodoroTimer(cfg["focus_min"], cfg["rest_min"], clock=wall)
        self.pets, self.notes = {}, {}
        self.work_on, self.cheer_until = {}, {}
        self._cursor = QCursor.pos()
        self._last_motion = mono()
        self._co_phase = co.OFF
        self._next_overtime = 0.0
        self.visible = True
        self.card = TimerCard(cfg["on_top"])
        self.chip = Chip(cfg["on_top"])
        self.card_owner = None
        self._settings = None
        self.tray = None

        finished = self.timer.restore(cfg.get("timer") or {}) if cfg.get("timer") else None
        self.timer.focus_min, self.timer.rest_min = int(cfg["focus_min"]), int(cfg["rest_min"])
        if finished and self.debug:
            print("자리를 비운 사이 타이머가 끝났습니다:", finished)

        for ch in cfg["enabled"]:
            self._add_pet(ch)
        self.card.primary_clicked.connect(self._primary)
        self.card.reset_clicked.connect(self._reset)
        self.card.cheer_clicked.connect(self.cheer_all)
        self.card.settings_clicked.connect(self.open_settings)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(250)
        self._motion_timer = QTimer(self)
        self._motion_timer.timeout.connect(self._motion)
        self._motion_timer.start(33)
        self._resolve()
        self._refresh_ui()

    # ── 만들기 / 없애기 ────────────────────────────────────────────────────
    def _log(self, *a):
        if self.debug:
            print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

    def _add_pet(self, ch):
        pc = self.cfg["pets"][ch]
        pet = Pet(ch, self.bank, scale=float(pc.get("scale", 0.5)), opacity=float(self.cfg["opacity"]),
                  on_top=self.cfg["on_top"])
        pet.clicked.connect(self._pet_clicked)
        pet.context_requested.connect(self._pet_menu)
        pet.moved.connect(self._pet_moved)
        pet.drag_ended.connect(self._pet_drag_ended)
        pet.wheel_scaled.connect(self._pet_wheel)
        self.pets[ch] = pet

        note = self.store.ensure(ch, STARTER_TEXT)
        w = PostIt(note, self.store, on_top=self.cfg["on_top"])
        w.set_mini_scale(mini_scale_for(pet.scale))
        w.layout_changed.connect(lambda _id, c=ch: self._follow(c))
        w.task_completed.connect(lambda _id, c=ch: self.cheer(c, 2.0))
        self.notes[ch] = w
        self._place_initial(ch)
        pet.show()
        w.show()
        self._follow(ch)
        self.store.save()

    def _remove_pet(self, ch):
        if ch in self.notes:
            self.notes[ch].flush_now()
            self.notes[ch].close()
            del self.notes[ch]
        if ch in self.pets:
            self.pets[ch].close()
            del self.pets[ch]
        self.work_on.pop(ch, None)
        if self.card_owner is not None and self.card_owner.char == ch:
            self.card.hide()
            self.card_owner = None

    def _place_initial(self, ch):
        pc = self.cfg["pets"][ch]
        pet = self.pets[ch]
        if pc.get("x") is not None and pc.get("y") is not None:
            probe = QPoint(int(pc["x"]) + pet.width() // 2, int(pc["y"]) + pet.height() // 2)
            if QApplication.screenAt(probe) is not None:
                pet.move(int(pc["x"]), int(pc["y"]))
                return
        area = QApplication.primaryScreen().availableGeometry()
        order = [c for c in self.cfg["enabled"] if c != self.cfg["leader"]] + [self.cfg["leader"]]   # 대표가 가장 오른쪽
        idx = order.index(ch) if ch in order else 0
        step = int(pet.width() * 0.78)
        right = area.right() - 24 - (len(order) - 1 - idx) * step
        pet.move(right - pet.width(), area.bottom() + 1 - pet.height())

    # ── 쪽지 따라다니기 ────────────────────────────────────────────────────
    def _follow(self, ch):
        pet, note = self.pets.get(ch), self.notes.get(ch)
        if pet is None or note is None:
            return
        note.set_swing(pet.swing())
        note.place_above(pet.anchor_global())
        if self.card.isVisible() and self.card_owner is pet:
            self._place_card()

    def _pet_moved(self, pet):
        self._follow(pet.char)

    def _pet_drag_ended(self, pet):
        self._save_positions()

    def _place_card(self):
        pet = self.card_owner
        if pet is None:
            return
        note = self.notes.get(pet.char)
        top = note.geometry().top() if note is not None else pet.geometry().top()
        self.card.place_above(top, pet.geometry().center().x())

    # ── 움직임 틱 (30Hz, 한가하면 10Hz) ────────────────────────────────────
    def _motion(self):
        now = self.mono()
        dt = max(0.0, min(0.2, now - self._last_motion))
        self._last_motion = now
        active = False
        for ch, pet in self.pets.items():
            pet.tick(now, dt)
            self._follow(ch)
            note = self.notes.get(ch)
            active = active or pet.intensity > 0.02 or pet.busy() or (note is not None and note.alerting())
        self._motion_timer.setInterval(33 if active else 100)
        if self.chip.isVisible():
            self._place_chip()

    def _place_chip(self):
        pet = self.pets.get(self.cfg["leader"])
        note = self.notes.get(self.cfg["leader"])
        if pet is None:
            return
        top = note.geometry().top() if note is not None else pet.geometry().top()
        self.chip.place_above(top, pet.geometry().center().x())

    # ── 주기 처리 (4Hz) ────────────────────────────────────────────────────
    def _poll(self):
        now = self.mono()
        events = []
        if self.cfg["react"] and self.probe.available:
            cur = QCursor.pos()
            moved = (cur - self._cursor).manhattanLength() > 2
            self._cursor = cur
            self.reactor.feed(now, self.probe.idle_ms(), moved)
            events = self.reactor.update(now)
        elif self.reactor.state != wr.IDLE or self.reactor.intensity:
            self.reactor = wr.WorkReactor()
            self.work_on.clear()
        for ev in events:
            self._on_reactor_event(ev)

        finished = self.timer.tick()
        if finished:
            self._save_timer_state()
            if finished == te.FOCUS:
                self.cheer_all(2.5, force_hop=True)
        self._clockout(now)
        self._resolve()
        self._refresh_ui()

    def _on_reactor_event(self, ev):
        self._log("reactor:", ev)
        leader = self.cfg["leader"]
        if ev == "focus_start":
            self.work_on[leader] = True
        elif ev == "together_start":
            t = 1.5
            for ch in [c for c in self.pets if c != leader]:        # 짧은 시차를 두고 차례로 합류
                t += random.uniform(1.0, 2.5)
                QTimer.singleShot(int(t * 1000), lambda c=ch: self._join(c))
        elif ev == "settle":
            for ch in list(self.pets):
                QTimer.singleShot(int(random.uniform(0.0, 3.0) * 1000), lambda c=ch: self._leave(c))
        elif ev == "nod":
            who = [c for c, p in self.pets.items() if p.pose == "focus"]
            if who:
                self.pets[random.choice(who)].nod()
        elif ev == "hop":
            who = [c for c, p in self.pets.items() if p.pose == "focus"]
            if who:
                self.cheer(random.choice(who), 0.9)

    def _join(self, ch):
        if ch in self.pets and self.reactor.state == wr.TOGETHER:
            self.work_on[ch] = True
            self._resolve()

    def _leave(self, ch):
        if self.reactor.state == wr.IDLE:
            self.work_on[ch] = False
            self._resolve()

    # ── 포즈 결정 ──────────────────────────────────────────────────────────
    def desired(self, ch):
        now, t = self.mono(), self.timer
        if t.phase == te.REST and t.status in (te.RUNNING, te.PAUSED):
            return "rest", 0.0
        if t.phase == te.FOCUS and t.status == te.DONE:
            return "cheer", 0.0
        if now < self.cheer_until.get(ch, 0.0):
            return "cheer", 0.0
        if t.phase == te.FOCUS and t.status == te.PAUSED:
            return "rest", 0.0
        base = self.reactor.intensity
        if t.phase == te.FOCUS and t.status == te.RUNNING:
            return "focus", max(base, 0.12)                       # 무활동이면 움직임만 잦아듦
        if self.work_on.get(ch):
            return "focus", base * (1.0 if ch == self.cfg["leader"] else 0.85)
        return "base", 0.0

    def _resolve(self):
        for ch, pet in self.pets.items():
            pose, inten = self.desired(ch)
            pet.set_pose(pose)
            pet.intensity = inten

    def cheer(self, ch, seconds=2.0, delay=0.0):
        def go():
            if ch in self.pets:
                self.cheer_until[ch] = self.mono() + seconds
                self.pets[ch].hop()
                self._resolve()
        if delay > 0:
            QTimer.singleShot(int(delay * 1000), go)
        else:
            go()

    def cheer_all(self, seconds=2.5, force_hop=False):
        for i, ch in enumerate(self.pets):
            self.cheer(ch, seconds, delay=0.0 if i == 0 else random.uniform(0.1, 0.5) * i)

    # ── 퇴근 ───────────────────────────────────────────────────────────────
    def schedule(self):
        c = self.cfg["clockout"]
        return co.Schedule(enabled=bool(c["enabled"]), time=c["time"], days=tuple(c["days"]),
                           warn=tuple(c["warn"]), skip_date=c.get("skip_date", ""))

    def _clockout(self, now):
        phase, left = co.status(self.now_fn(), self.schedule())
        leader_note = self.notes.get(self.cfg["leader"])
        if phase != self._co_phase:
            self._log("퇴근 단계:", self._co_phase, "→", phase)
            if phase in (co.WARN30, co.WARN10) and leader_note is not None:
                leader_note.alert(6.0)                            # 쪽지가 흔들리며 알려 줌(말풍선 없음)
            elif phase == co.NOW:
                for note in self.notes.values():
                    note.alert(5.0)
                self.cheer_all(4.0)
                self._next_overtime = now + 1800
            self._co_phase = phase
        if phase == co.NOW:
            badge = "퇴근!"
        elif phase == co.OVER and self.reactor.state != wr.IDLE:
            badge = "야근"
            if now >= self._next_overtime and leader_note is not None:     # 30분에 한 번 살짝 흔들기
                leader_note.alert(4.0)
                self._next_overtime = now + 1800
        else:
            badge = ""
        for note in self.notes.values():
            note.set_badge(badge)
        return phase, left

    # ── 카드 / 칩 ──────────────────────────────────────────────────────────
    @staticmethod
    def _mmss(sec):
        s = int(math.ceil(sec))
        return f"{s // 60:02d}:{s % 60:02d}"

    def _card_state(self):
        t = self.timer
        if t.status == te.IDLE:
            return "대기", self._mmss(t.duration(te.FOCUS)), "시작"
        label = "집중" if t.phase == te.FOCUS else "휴식"
        if t.status == te.RUNNING:
            return label, self._mmss(t.remaining()), "일시정지"
        if t.status == te.PAUSED:
            return label + " (멈춤)", self._mmss(t.remaining()), "이어하기"
        return "집중 완료!", "00:00", "휴식 시작"

    def _refresh_ui(self):
        phase, left = co.status(self.now_fn(), self.schedule())
        leave_text, leave_color, chip_color = "", "#7b7562", "#8A8AA0"
        if phase in (co.FAR, co.WARN30, co.WARN10):
            leave_text = "퇴근까지 " + co.format_left(left)
            leave_color = {co.FAR: "#7b7562", co.WARN30: "#D98324", co.WARN10: "#E5484D"}[phase]
            chip_color = {co.FAR: "#8A8AA0", co.WARN30: "#F0A030", co.WARN10: "#E5484D"}[phase]
        elif phase == co.NOW:
            leave_text, leave_color, chip_color = "퇴근 시간이에요!", "#E5484D", "#E5484D"
        elif phase == co.OVER:
            leave_text, leave_color = "퇴근 시간이 지났어요", "#E5484D"
        if self.card.isVisible():
            a, b, c = self._card_state()
            self.card.refresh(a, b, c, leave_text, leave_color)
        # 칩: 타이머가 돌면 남은 시간, 아니면 퇴근이 가까울 때만
        text, color = "", "#6C7BF0"
        t = self.timer
        if t.status in (te.RUNNING, te.PAUSED):
            sign = "" if t.status == te.RUNNING else "⏸ "
            text = f"{sign}{'집중' if t.phase == te.FOCUS else '휴식'} {self._mmss(t.remaining())}"
            color = "#6C7BF0" if t.phase == te.FOCUS else "#4FA77B"
        elif t.status == te.DONE:
            text, color = "집중 완료!", "#E8708A"
        elif phase in (co.WARN30, co.WARN10) or (phase == co.FAR and left < 3600):
            text, color = "퇴근 " + co.format_left(left), chip_color
        elif phase == co.NOW:
            text, color = "퇴근!", "#E5484D"
        show_chip = bool(text) and self.visible and not self.card.isVisible() and self.cfg["leader"] in self.pets
        if show_chip:
            self.chip.set_content(text, color)
            if not self.chip.isVisible():
                self.chip.show()
            self._place_chip()
        else:
            self.chip.hide()

    def _save_timer_state(self):
        self.cfg["timer"] = self.timer.to_dict()
        self.save_config()

    def _primary(self):
        t = self.timer
        if t.status == te.IDLE:
            t.start_focus()
        elif t.status == te.RUNNING:
            t.pause()
        elif t.status == te.PAUSED:
            t.resume()
        elif t.status == te.DONE:
            t.start_rest()
        self._save_timer_state()
        self._resolve()
        self._refresh_ui()

    def _reset(self):
        self.timer.reset()
        self._save_timer_state()
        self._resolve()
        self._refresh_ui()

    # ── 캐릭터 조작 ────────────────────────────────────────────────────────
    def _pet_clicked(self, pet):
        if self.card.isVisible() and self.card_owner is pet:
            self.card.hide()
            return
        self.card_owner = pet
        a, b, c = self._card_state()
        self.card.refresh(a, b, c)
        self.card.show()
        self._place_card()
        self.chip.hide()
        self._refresh_ui()

    def _pet_wheel(self, pet, factor, everyone):
        for p in (self.pets.values() if everyone else [pet]):
            self.set_pet_scale(p, p.scale * factor)

    def set_pet_scale(self, pet, s):
        pet.set_scale(s)
        self.notes[pet.char].set_mini_scale(mini_scale_for(pet.scale))
        self._follow(pet.char)
        self._save_positions()

    def _pet_menu(self, pet):
        m = QMenu()
        m.addAction("타이머 카드").triggered.connect(lambda: self._pet_clicked(pet))
        note = self.notes[pet.char]
        m.addAction("포스트잇 접기" if note.is_open() else "포스트잇 펼치기").triggered.connect(note.toggle)
        m.addAction("응원").triggered.connect(self.cheer_all)
        m.addSeparator()
        sm = m.addMenu(f"{CHAR_LABEL[pet.char]} 크기  (휠 · Ctrl+휠=모두)")
        for label, s in SIZE_PRESETS:
            a = sm.addAction(f"{label}  ({s:g}배)")
            a.setCheckable(True)
            a.setChecked(abs(pet.scale - s) < 0.02)
            a.triggered.connect(lambda _=False, v=s, p=pet: self.set_pet_scale(p, v))
        am = m.addMenu("모두 같은 크기로")
        for label, s in SIZE_PRESETS:
            am.addAction(f"{label}  ({s:g}배)").triggered.connect(
                lambda _=False, v=s: [self.set_pet_scale(p, v) for p in self.pets.values()])
        om = m.addMenu("캐릭터 투명도")
        for pct in (40, 55, 70, 85, 100):
            a = om.addAction(f"{pct}%")
            a.setCheckable(True)
            a.setChecked(abs(self.cfg["opacity"] * 100 - pct) < 3)
            a.triggered.connect(lambda _=False, v=pct / 100: self.set_opacity(v))
        m.addSeparator()
        m.addAction("설정").triggered.connect(self.open_settings)
        m.addAction("숨기기").triggered.connect(lambda: self.set_visible(False))
        m.addAction("프로그램 종료").triggered.connect(self.quit_app)
        m.exec_(QCursor.pos())

    def set_opacity(self, v):
        self.cfg["opacity"] = v
        for p in self.pets.values():
            p.set_opacity(v)
        self.save_config()

    def set_visible(self, on):
        self.visible = on
        for w in list(self.pets.values()) + list(self.notes.values()):
            w.setVisible(on)
        if not on:
            self.card.hide()
            self.chip.hide()

    # ── 설정 ───────────────────────────────────────────────────────────────
    def open_settings(self):
        if self._settings is not None and self._settings.isVisible():
            self._settings.raise_()
            return
        dlg = SettingsDialog(self.cfg, self.probe, self.reactor)
        self._settings = dlg
        if dlg.exec_():
            self.apply_settings(dlg.values())

    def apply_settings(self, v):
        self.cfg["focus_min"], self.cfg["rest_min"] = v["focus_min"], v["rest_min"]
        self.timer.focus_min, self.timer.rest_min = v["focus_min"], v["rest_min"]
        self.cfg["react"] = v["react"]
        self.cfg["clockout"].update(v["clockout"])
        self.cfg["leader"] = v["leader"]
        if not v["react"]:
            self.reactor = wr.WorkReactor()
            self.work_on.clear()
        if v["on_top"] != self.cfg["on_top"]:
            self.cfg["on_top"] = v["on_top"]
            from PyQt5.QtCore import Qt
            for w in list(self.pets.values()) + list(self.notes.values()) + [self.card, self.chip]:
                vis = w.isVisible()
                w.setWindowFlag(Qt.WindowStaysOnTopHint, v["on_top"])
                if vis:
                    w.show()
        for ch in CHARS:
            if ch in v["enabled"] and ch not in self.pets:
                self.cfg["enabled"] = v["enabled"]
                self._add_pet(ch)
            elif ch not in v["enabled"] and ch in self.pets:
                self._save_positions()
                self._remove_pet(ch)
        self.cfg["enabled"] = v["enabled"]
        self.save_config()
        self._resolve()
        self._refresh_ui()

    # ── 저장 ───────────────────────────────────────────────────────────────
    def _save_positions(self):
        for ch, pet in self.pets.items():
            self.cfg["pets"][ch].update(x=pet.x(), y=pet.y(), scale=round(pet.scale, 3))
        self.save_config()

    def save_config(self):
        try:
            self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
            self.cfg_path.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def make_tray(self, app):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return None
        pm = self.bank.raw(self.cfg["leader"], "base").scaled(64, 64)
        tray = QSystemTrayIcon(QIcon(pm), app)
        tray.setToolTip("먼작귀 응원 위젯")
        menu = QMenu()
        menu.addAction("보이기 / 숨기기").triggered.connect(lambda: self.set_visible(not self.visible))
        menu.addAction("설정").triggered.connect(self.open_settings)
        menu.addAction("오늘은 퇴근 알림 끄기").triggered.connect(self._skip_today)
        menu.addAction("종료").triggered.connect(self.quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(lambda r: self.set_visible(not self.visible) if r == QSystemTrayIcon.Trigger else None)
        tray.show()
        self.tray = tray
        return tray

    def _skip_today(self):
        self.cfg["clockout"]["skip_date"] = self.now_fn().date().isoformat()
        self.save_config()

    def quit_app(self):
        for note in self.notes.values():
            note.flush_now()
        self.store.save()
        self._save_positions()
        self._save_timer_state()
        QApplication.quit()
