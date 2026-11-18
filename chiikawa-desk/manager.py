"""전체 조립: 여러 캐릭터 · 머리 위 물건(포스트잇/타이머/퇴근 시계).

캐릭터들은 스스로 일한다: 다 같이 키보드를 두드리는 '일하는 시간'과, 서로 다른 동작을 하는 짧은 '쉬는 시간'이
번갈아 온다(시작·끝은 캐릭터마다 어긋남). 사용자의 입력은 전혀 읽지 않는다.

모드 결정 우선순위(위가 먼저).
  1) 휴식 타이머(진행·일시정지)  → 휴식 포즈 고정
  2) 집중 완료                   → 응원 포즈(휴식 시작 버튼을 누를 때까지)
  3) 응원 이벤트(버튼·할 일 완료·퇴근 정각) → 잠깐 응원 후 복귀
  4) 집중 타이머 일시정지         → 휴식 포즈
  5) 집중 타이머 진행 중          → 계속 키보드를 두드린다
  6) 일하는 시간                  → 키보드를 두드린다(캐릭터마다 박자·컷이 다름)
  7) 쉬는 시간                    → 서로 다른 동작을 계속 이어간다
"""
import json
import math
import random
import time
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QObject, QPoint, Qt, QTimer
from PyQt5.QtGui import QCursor, QIcon
from PyQt5.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import clock_out as co
import timer_engine as te
from items import ClockItem, TimerItem
from notes_store import NoteStore
from panel import CARRY_CHOICES, SettingsDialog, normalize_carry
from pet import CHAR_LABEL, CHARS, SIZE_PRESETS, Pet
from postit import PostIt

STARTER_TEXT = "할 일\n" + "☐ "

DEFAULT_CONFIG = {
    "enabled": list(CHARS),
    "leader": "chiikawa",
    "carry": {"chiikawa": "memo", "hachiware": "memo", "usagi": "timer"},   # 머리 위에 올리는 것
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
    cfg["carry"] = normalize_carry(cfg["carry"], cfg["enabled"])
    return cfg


def mini_scale_for(pet_scale):
    """캐릭터가 작을수록 머리 위 쪽지도 작게."""
    return max(0.6, min(1.25, 0.55 + 0.9 * pet_scale))


class PetManager(QObject):
    WORK_RANGE = (70.0, 150.0)       # 다 같이 키보드를 두드리는 시간(초)
    BREAK_RANGE = (16.0, 38.0)       # 서로 다른 동작을 하는 쉬는 시간(초)

    def __init__(self, cfg, cfg_path, store, bank, timer=None,
                 mono=time.monotonic, wall=time.time, now_fn=datetime.now, later=None, seed=None, debug=False):
        super().__init__()
        self.cfg, self.cfg_path, self.store, self.bank = cfg, Path(cfg_path), store, bank
        self.mono, self.now_fn, self.debug = mono, now_fn, debug
        self.later = later or (lambda delay, fn: QTimer.singleShot(int(delay * 1000), fn))
        self.rng = random.Random(seed)
        self.timer = timer or te.PomodoroTimer(cfg["focus_min"], cfg["rest_min"], clock=wall)
        self.pets, self.items = {}, {}
        self.work_on, self.cheer_until = {}, {}
        self._applied, self._pending = {}, {}
        self._last_motion = mono()
        self.block = "work"                                  # 지금이 일하는 시간인지 쉬는 시간인지
        self._block_until = mono() + self.rng.uniform(*self.WORK_RANGE)
        self._next_nod = mono() + self.rng.uniform(40, 90)
        self._wave = {}
        self._co_phase = co.OFF
        self._dirty, self._last_save = False, mono()
        self.visible = True
        self._settings = None
        self.tray = None

        finished = self.timer.restore(cfg.get("timer") or {}) if cfg.get("timer") else None
        self.timer.focus_min, self.timer.rest_min = int(cfg["focus_min"]), int(cfg["rest_min"])
        if finished and self.debug:
            print("자리를 비운 사이 타이머가 끝났습니다:", finished)

        for ch in cfg["enabled"]:
            self._add_pet(ch)
        self._rebuild_items()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start(250)
        self._motion_timer = QTimer(self)
        self._motion_timer.timeout.connect(self._motion)
        self._motion_timer.start(33)
        for ch in self.pets:                                  # 처음엔 모두 일하는 모습으로 시작(시작 시점은 조금씩 다르게)
            self.work_on[ch] = True
        self._resolve(first=True)
        self._refresh_items()

    # ── 만들기 / 없애기 ────────────────────────────────────────────────────
    def _log(self, *a):
        if self.debug:
            print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

    def _add_pet(self, ch):
        pc = self.cfg["pets"][ch]
        pet = Pet(ch, self.bank, scale=float(pc.get("scale", 0.5)), opacity=float(self.cfg["opacity"]),
                  on_top=self.cfg["on_top"], seed=self.rng.random(), now=self.mono())
        pet.peers = lambda c=ch: {p.action_name() for k, p in self.pets.items() if k != c and p.action_name()}
        pet.clicked.connect(self._pet_clicked)
        pet.context_requested.connect(self._pet_menu)
        pet.moved.connect(self._pet_moved)
        pet.drag_ended.connect(self._pet_drag_ended)
        pet.group_step.connect(self._group_step)
        pet.wheel_scaled.connect(self._pet_wheel)
        self.pets[ch] = pet
        self._place_initial(ch)
        pet.show()

    def _remove_pet(self, ch):
        self._drop_item(ch)
        if ch in self.pets:
            self.pets[ch].close()
            del self.pets[ch]
        for d in (self.work_on, self._applied, self._pending):
            d.pop(ch, None)

    def _place_initial(self, ch):
        pc = self.cfg["pets"][ch]
        pet = self.pets[ch]
        if pc.get("x") is not None and pc.get("y") is not None:
            probe = QPoint(int(pc["x"]) + pet.width() // 2, int(pc["y"]) + pet.height() // 2)
            if QApplication.screenAt(probe) is not None:
                pet.move(int(pc["x"]), int(pc["y"]))
                return
        self._place_in_row(ch)

    def _place_in_row(self, ch):
        pet = self.pets[ch]
        area = QApplication.primaryScreen().availableGeometry()
        order = [c for c in self.cfg["enabled"] if c != self.cfg["leader"]] + [self.cfg["leader"]]   # 대표가 가장 오른쪽
        idx = order.index(ch) if ch in order else 0
        step = int(pet.width() * 0.78)
        right = area.right() - 24 - (len(order) - 1 - idx) * step
        pet.move(right - pet.width(), area.bottom() + 1 - pet.height())

    def gather(self):
        """흩어진 캐릭터들을 화면 아래 오른쪽에 한 줄로 모은다."""
        for ch in self.pets:
            self._place_in_row(ch)
        self._save_positions()

    # ── 머리 위 물건 ───────────────────────────────────────────────────────
    def _drop_item(self, ch):
        it = self.items.pop(ch, None)
        if it is not None:
            if isinstance(it, PostIt):
                it.flush_now()
            it.close()

    def _rebuild_items(self):
        self.cfg["carry"] = normalize_carry(self.cfg["carry"], list(self.pets))
        for ch in list(self.items):
            self._drop_item(ch)
        for ch, pet in self.pets.items():
            kind = self.cfg["carry"].get(ch, "none")
            it = None
            if kind == "memo":
                it = PostIt(self.store.ensure(ch, STARTER_TEXT), self.store, on_top=self.cfg["on_top"])
                it.task_completed.connect(lambda _id, c=ch: self.cheer(c, 2.0))
            elif kind == "timer":
                it = TimerItem(self.cfg["on_top"])
                it.primary_clicked.connect(self._primary)
                it.reset_clicked.connect(self._reset)
                it.cheer_clicked.connect(self.cheer_all)
                it.settings_clicked.connect(self.open_settings)
            elif kind == "clock":
                it = ClockItem(self.cfg["on_top"])
                it.skip_clicked.connect(self._skip_today)
                it.settings_clicked.connect(self.open_settings)
            if it is None:
                continue
            it.kind_name = kind
            it.set_mini_scale(mini_scale_for(pet.scale))
            it.layout_changed.connect(lambda _w, c=ch: self._follow(c))
            it.drag_step.connect(lambda step, shift, c=ch: self._item_drag(c, step, shift))
            self.items[ch] = it
            self._follow(ch)
            if self.visible:
                it.show()
        self.store.save()
        self._refresh_items()

    def item_of(self, kind):
        return next((it for it in self.items.values() if getattr(it, "kind_name", "") == kind), None)

    def notes(self):
        return {ch: it for ch, it in self.items.items() if isinstance(it, PostIt)}

    def set_carry(self, ch, kind):
        self.cfg["carry"][ch] = kind
        self._rebuild_items()
        self.save_config()

    def _follow(self, ch):
        pet, it = self.pets.get(ch), self.items.get(ch)
        if pet is None or it is None:
            return
        it.set_swing(pet.swing())
        it.place_above(pet.anchor_global())

    def _pet_moved(self, pet):
        self._follow(pet.char)
        self._dirty = True

    def _pet_drag_ended(self, _pet):
        self._save_positions()

    def _move_all(self, step, skip=None):
        for p in self.pets.values():
            if p is not skip:
                p.move(p.pos() + step)

    def _group_step(self, pet, step):
        self._move_all(step, skip=pet)

    def _item_drag(self, ch, step, shift):
        pet = self.pets.get(ch)
        if pet is None:
            return
        pet.move(pet.pos() + step)
        if shift:
            self._move_all(step, skip=pet)

    # ── 움직임 틱 (30Hz, 한가하면 10Hz) ────────────────────────────────────
    def _motion(self):
        now = self.mono()
        dt = max(0.0, min(0.2, now - self._last_motion))
        self._last_motion = now
        active = False
        for ch, pet in self.pets.items():
            pet.tick(now, dt)
            self._follow(ch)
            it = self.items.get(ch)
            active = active or pet.busy() or (it is not None and it.alerting())
        self._motion_timer.setInterval(33 if active else 100)

    # ── 주기 처리 (4Hz) ────────────────────────────────────────────────────
    def _poll(self):
        now = self.mono()
        if now >= self._block_until:
            self._switch_block(now)
        self._wiggle_intensity(now)
        if now >= self._next_nod and self.block == "work":
            self._next_nod = now + self.rng.uniform(40, 90)
            who = [c for c, p in self.pets.items() if p.mode == "type"]
            if who:
                self.pets[self.rng.choice(who)].nod()                 # 가끔 한 캐릭터가 끄덕끄덕
        finished = self.timer.tick()
        if finished:
            self._save_timer_state()
            if finished == te.FOCUS:
                self.cheer_all(2.8)
        self._clockout(now)
        if self._dirty and now - self._last_save > 2.0:                  # 끌어서 옮긴 위치를 가끔 저장
            self._dirty, self._last_save = False, now
            self._save_positions()
        self._resolve()
        self._refresh_items()

    def _switch_block(self, now, mode=None, immediate=False):
        """일하는 시간 ↔ 쉬는 시간. 시작·끝은 캐릭터마다 어긋난다."""
        self.block = mode or ("break" if self.block == "work" else "work")
        lo, hi = self.WORK_RANGE if self.block == "work" else self.BREAK_RANGE
        self._block_until = now + self.rng.uniform(lo, hi)
        self._log("블록:", self.block)
        on = self.block == "work"
        for ch in list(self.pets):
            if immediate:
                self.work_on[ch] = on
            else:
                spread = 3.0 if on else 1.0              # 쉬는 시간이 되면 1초 안에 키보드에서 손을 뗀다
                self.later(self.rng.uniform(0.0, spread), lambda c=ch, v=on: self._set_work(c, v))

    def _set_work(self, ch, on):
        if ch in self.pets and (on == (self.block == "work")):
            self.work_on[ch] = on
            self._resolve()

    def _wiggle_intensity(self, now):
        """두드리는 세기를 캐릭터마다 천천히 다르게 오르내린다."""
        for i, (ch, pet) in enumerate(self.pets.items()):
            if pet.mode == "type":
                pet.intensity = max(0.3, min(1.0, 0.65 + 0.3 * math.sin(now / (6.0 + 2.3 * i) + 1.7 * i)))

    # ── 모드 결정 ──────────────────────────────────────────────────────────
    def desired(self, ch):
        """→ (종류, 인자, 움직임 강도). 종류: static(포즈) / type(키보드) / idle(쉬는 동작)"""
        now, t = self.mono(), self.timer
        if t.phase == te.REST and t.status in (te.RUNNING, te.PAUSED):
            return "static", "rest", 0.0
        if t.phase == te.FOCUS and t.status == te.DONE:
            return "static", "cheer", 0.0
        if now < self.cheer_until.get(ch, 0.0):
            return "static", "cheer", 0.0
        if t.phase == te.FOCUS and t.status == te.PAUSED:
            return "static", "rest", 0.0
        if (t.phase == te.FOCUS and t.status == te.RUNNING) or self.work_on.get(ch):
            pet = self.pets.get(ch)
            return "type", None, (pet.intensity if pet is not None and pet.mode == "type" else 0.65)
        return "idle", None, 0.0

    def _apply(self, ch, kind, arg, inten):
        pet = self.pets.get(ch)
        if pet is None:
            return
        if kind == "static":
            pet.set_static(arg, inten)
        elif kind == "type":
            pet.set_typing(inten)
        else:
            pet.set_idle()
        self._applied[ch] = (kind, arg)

    def _commit(self, ch):
        self._pending.pop(ch, None)
        kind, arg, inten = self.desired(ch)
        self._apply(ch, kind, arg, inten)

    def _resolve(self, first=False):
        for ch, pet in self.pets.items():
            kind, arg, inten = self.desired(ch)
            key = (kind, arg)
            if self._applied.get(ch) == key:
                if kind != "idle":
                    pet.intensity = inten
                continue
            if self._pending.get(ch) == key:
                continue
            if first or self._applied.get(ch) is None or kind == "type":
                self._apply(ch, kind, arg, inten)
            else:                                              # 같은 순간에 똑같이 바뀌지 않도록 캐릭터마다 조금씩 늦춤
                self._pending[ch] = key
                self.later(pet.rng.uniform(0.0, 0.55), lambda c=ch: self._commit(c))

    def cheer(self, ch, seconds=2.0, delay=0.0):
        def go():
            if ch in self.pets:
                self.cheer_until[ch] = self.mono() + seconds
                self.pets[ch].hop()
                self._resolve()
        if delay > 0:
            self.later(delay, go)
        else:
            go()

    def cheer_all(self, seconds=2.5):
        for ch, pet in self.pets.items():        # 시작 시점·길이가 캐릭터마다 다르다
            self.cheer(ch, seconds * pet.rng.uniform(0.8, 1.25), delay=pet.rng.uniform(0.0, 0.7))

    # ── 퇴근 ───────────────────────────────────────────────────────────────
    def schedule(self):
        c = self.cfg["clockout"]
        return co.Schedule(enabled=bool(c["enabled"]), time=c["time"], days=tuple(c["days"]),
                           warn=tuple(c["warn"]), skip_date=c.get("skip_date", ""))

    def _alert_target(self):
        return self.item_of("clock") or self.item_of("timer") or self.items.get(self.cfg["leader"]) or next(iter(self.items.values()), None)

    def _clockout(self, now):
        phase, left = co.status(self.now_fn(), self.schedule())
        target = self._alert_target()
        if phase != self._co_phase:
            self._log("퇴근 단계:", self._co_phase, "→", phase)
            if phase in (co.WARN30, co.WARN10) and target is not None:
                target.alert(6.0)                                 # 머리 위 물건이 흔들리며 알려 줌(말풍선 없음)
            elif phase == co.NOW:
                for it in self.items.values():
                    it.alert(5.0)
                self.cheer_all(4.0)
            self._co_phase = phase
        badge = "퇴근!" if phase == co.NOW else ""
        for it in self.items.values():
            if isinstance(it, PostIt):
                it.set_badge(badge)
        return phase, left

    # ── 타이머·퇴근 시계 표시 ──────────────────────────────────────────────
    @staticmethod
    def _mmss(sec):
        s = int(math.ceil(sec))
        return f"{s // 60:02d}:{s % 60:02d}"

    def _timer_view(self):
        t = self.timer
        if t.status == te.IDLE:
            return "idle", "대기", self._mmss(t.duration(te.FOCUS)), "시작"
        label = "집중" if t.phase == te.FOCUS else "휴식"
        if t.status == te.RUNNING:
            return ("focus" if t.phase == te.FOCUS else "rest"), label, self._mmss(t.remaining()), "일시정지"
        if t.status == te.PAUSED:
            return "paused", label + " 멈춤", self._mmss(t.remaining()), "이어하기"
        return "done", "완료!", "00:00", "휴식 시작"

    def _refresh_items(self):
        phase, left = co.status(self.now_fn(), self.schedule())
        leave_text, leave_color = "", "#7b7562"
        if phase in (co.FAR, co.WARN30, co.WARN10):
            leave_text = "퇴근까지 " + co.format_left(left)
            leave_color = {co.FAR: "#7b7562", co.WARN30: "#D98324", co.WARN10: "#E5484D"}[phase]
        elif phase == co.NOW:
            leave_text, leave_color = "퇴근 시간이에요!", "#E5484D"
        elif phase == co.OVER:
            leave_text, leave_color = "퇴근 시간이 지났어요", "#E5484D"
        timer_item = self.item_of("timer")
        if timer_item is not None:
            kind, label, text, primary = self._timer_view()
            timer_item.refresh(kind, label, text, primary, leave_text, leave_color)
        clock_item = self.item_of("clock")
        if clock_item is not None:
            if phase == co.OFF:
                big, sub = "--", "오늘은 퇴근 알림이 없어요"
            elif phase == co.NOW:
                big, sub = "퇴근!", "수고하셨어요"
            elif phase == co.OVER:
                big, sub = "지남", "퇴근 시간이 지났어요"
            else:
                big, sub = co.format_left(left), "퇴근까지 남은 시간"
            clock_item.refresh(phase, big, sub, self.cfg["clockout"]["time"])

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
        self._refresh_items()

    def _reset(self):
        self.timer.reset()
        self._save_timer_state()
        self._resolve()
        self._refresh_items()

    # ── 캐릭터 조작 ────────────────────────────────────────────────────────
    def _pet_clicked(self, pet):
        it = self.items.get(pet.char)
        if it is not None:
            it.toggle()
        else:
            self.cheer(pet.char, 1.6)                             # 아무것도 안 들고 있으면 반갑게 인사

    def _pet_wheel(self, pet, factor, everyone):
        for p in (self.pets.values() if everyone else [pet]):
            self.set_pet_scale(p, p.scale * factor)

    def set_pet_scale(self, pet, s):
        pet.set_scale(s)
        it = self.items.get(pet.char)
        if it is not None:
            it.set_mini_scale(mini_scale_for(pet.scale))
        self._follow(pet.char)
        self._save_positions()

    def _pet_menu(self, pet):
        m = QMenu()
        it = self.items.get(pet.char)
        if it is not None:
            m.addAction("머리 위 물건 접기" if it.is_open() else "머리 위 물건 펼치기").triggered.connect(it.toggle)
        m.addAction("응원").triggered.connect(lambda: self.cheer_all(2.5))
        cm = m.addMenu(f"{CHAR_LABEL[pet.char]} 머리 위에 올릴 것")
        for key, label in CARRY_CHOICES:
            a = cm.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.cfg["carry"].get(pet.char) == key)
            a.triggered.connect(lambda _=False, k=key, c=pet.char: self.set_carry(c, k))
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
        m.addAction("모두 한 줄로 모으기  (Shift+끌기 = 모두 이동)").triggered.connect(self.gather)
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
        for w in list(self.pets.values()) + list(self.items.values()):
            w.setVisible(on)

    # ── 설정 ───────────────────────────────────────────────────────────────
    def open_settings(self):
        if self._settings is not None and self._settings.isVisible():
            self._settings.raise_()
            return
        original = {ch: p.scale for ch, p in self.pets.items()}
        dlg = SettingsDialog(self.cfg, bank=self.bank, scales=original, on_live=self._live_scales)
        self._settings = dlg
        if dlg.exec_():
            self.apply_settings(dlg.values())
        else:
            self._live_scales(original)                          # 취소하면 크기를 원래대로

    def _live_scales(self, scales):
        """설정 창에서 크기를 조절하는 동안 실제 캐릭터에 바로 반영한다(저장은 확인을 누를 때)."""
        for ch, s in scales.items():
            pet = self.pets.get(ch)
            if pet is None:
                continue
            pet.set_scale(s)
            it = self.items.get(ch)
            if it is not None:
                it.set_mini_scale(mini_scale_for(pet.scale))
            self._follow(ch)

    def apply_settings(self, v):
        self.cfg["focus_min"], self.cfg["rest_min"] = v["focus_min"], v["rest_min"]
        self.timer.focus_min, self.timer.rest_min = v["focus_min"], v["rest_min"]
        self.cfg["clockout"].update(v["clockout"])
        if v["enabled"] and self.cfg["leader"] not in v["enabled"]:
            self.cfg["leader"] = v["enabled"][0]
        if v["on_top"] != self.cfg["on_top"]:
            self.cfg["on_top"] = v["on_top"]
            for w in list(self.pets.values()) + list(self.items.values()):
                vis = w.isVisible()
                w.setWindowFlag(Qt.WindowStaysOnTopHint, v["on_top"])
                if vis:
                    w.show()
        for ch, s in v.get("scales", {}).items():
            self.cfg["pets"][ch]["scale"] = round(float(s), 3)
        self.cfg["enabled"] = v["enabled"]
        for ch in CHARS:
            if ch in v["enabled"] and ch not in self.pets:
                self._add_pet(ch)
            elif ch not in v["enabled"] and ch in self.pets:
                self._save_positions()
                self._remove_pet(ch)
        self._live_scales({ch: self.cfg["pets"][ch]["scale"] for ch in self.pets})
        self.cfg["carry"] = dict(v["carry"])
        for ch in self.pets:
            self.work_on.setdefault(ch, self.block == "work")
        self._rebuild_items()
        self._save_positions()
        self._resolve(first=True)
        self._refresh_items()

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
        ch = self.cfg["leader"] if self.cfg["leader"] in CHARS else CHARS[0]
        pm = self.bank.raw(f"{ch}_base").scaled(64, 64)
        tray = QSystemTrayIcon(QIcon(pm), app)
        tray.setToolTip("먼작귀 응원 위젯")
        menu = QMenu()
        menu.addAction("보이기 / 숨기기").triggered.connect(lambda: self.set_visible(not self.visible))
        menu.addAction("모두 한 줄로 모으기").triggered.connect(self.gather)
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
        for it in self.items.values():
            if isinstance(it, PostIt):
                it.flush_now()
        self.store.save()
        self._save_positions()
        self._save_timer_state()
        QApplication.quit()
