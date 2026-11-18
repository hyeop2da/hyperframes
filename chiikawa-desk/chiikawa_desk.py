#!/usr/bin/env python3
"""치이카와 데스크톱 응원 위젯 (PyQt5)

바탕화면 위에 항상 떠 있는 투명 배경 치이카와가 내가 일하는 모습을 지켜보며 응원해 줍니다.

  * 키보드를 치면 → 잠깐 사용자 쪽을 쳐다본 뒤, 같이 키보드를 열심히 침 (타이핑 속도에 맞춰 계속 움직임)
  * 입력이 4초 멈추면 → 한숨 돌리고 다시 멍하니 깜빡임, 30~60초마다 랜덤 행동
  * 좌클릭 = 반응 / 좌드래그 = 이동 / 휠 = 크기 / 우클릭 = 메뉴

개인정보: 어떤 키를 눌렀는지는 읽거나 저장하지 않고, "입력이 있었다"는 사실만 사용합니다.
"""
import argparse
import json
import math
import random
import sys
import time
from collections import deque
from pathlib import Path

from PyQt5.QtCore import QPoint, QSize, Qt, QObject, QTimer, pyqtSignal
from PyQt5.QtGui import QCursor, QIcon, QPainter, QPixmap, QRegion, QTransform
from PyQt5.QtWidgets import (
    QActionGroup, QApplication, QMenu, QSystemTrayIcon, QWidget,
)

HERE = Path(__file__).resolve().parent
FRAME_DIR = HERE / "frames"
CONFIG_PATH = Path.home() / ".chiikawa_desk.json"
HOTKEY_TEXT = "Ctrl+Alt+C"

DEFAULTS = {
    "scale": 0.5,           # 시작 크기 (원본 대비)
    "opacity": 0.85,        # 반투명 (마우스를 올리면 100%)
    "x": None,
    "y": None,
    "keyboard": True,       # 키보드 입력 감지
    "notice_look": True,    # 타이핑 시작 때 먼저 사용자 쪽을 쳐다보기
    "focus_timeout": 4.0,   # 입력이 이 시간(초) 멈추면 타이핑 종료 (3~5초 권장)
    "random_min": 30,       # 랜덤 행동 간격(초)
    "random_max": 60,
    "sleep_after": 300,     # 아무 활동이 없으면 낮잠(초)
}

# 아주 작게도 줄일 수 있음 (0.08배 ≈ 원본의 8%)
SCALE_MIN, SCALE_MAX = 0.08, 3.0
SIZE_PRESETS = [("초소형", 0.1), ("아주 작게", 0.15), ("작게", 0.25), ("조금 작게", 0.35),
                ("보통", 0.5), ("크게", 0.8), ("아주 크게", 1.2)]

TYPE_A, TYPE_B = 12, 13     # 타이핑 스프라이트 행 (A: 기본 6칸, B: 변주)

# 행동 정의: 스프라이트 행(row, 1부터), 재생할 열 순서, 프레임당 ms
ACTIONS = {
    "cheer":  dict(label="응원하기",     row=5,  ms=130, cols=[1, 2, 3, 4, 5, 6, 4, 5, 6, 5, 4, 3, 2, 1]),
    "wave":   dict(label="손 흔들기",    row=6,  ms=120, cols=[1, 2, 3, 4, 5, 6, 3, 4, 5, 6, 3, 4, 5, 6, 2, 1]),
    "hearts": dict(label="하트 날리기",  row=11, ms=150, cols=[1, 2, 3, 4, 5, 6, 5, 6, 5, 4, 3, 2, 1]),
    "cry":    dict(label="울먹이기",     row=9,  ms=150, cols=[1, 2, 3, 4, 5, 6, 5, 6, 5, 6, 4, 3, 2, 1]),
    "angry":  dict(label="삐지기",       row=8,  ms=140, cols=[1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1]),
    "dizzy":  dict(label="어지러워하기", row=10, ms=140, cols=[1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 3, 2, 1]),
    "sweat":  dict(label="깜짝 놀라기",  row=7,  ms=140, cols=[1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1]),
}
RANDOM_WEIGHTS = {"cheer": 3, "wave": 3, "hearts": 2, "cry": 1, "angry": 1, "dizzy": 1, "sweat": 1}


# ──────────────────────────────────────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────────────────────────────────────
def load_config(reset=False):
    cfg = dict(DEFAULTS)
    if not reset and CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k in DEFAULTS:
                if k in data:
                    cfg[k] = data[k]
        except (OSError, ValueError):
            pass
    return cfg


def save_config(cfg):
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# 스프라이트
# ──────────────────────────────────────────────────────────────────────────────
class SpriteBank:
    """frames/*.png 를 읽어 (크기·좌우반전별) 캐시해 두는 저장소."""

    def __init__(self, frame_dir):
        manifest = json.loads((frame_dir / "manifest.json").read_text(encoding="utf-8"))
        self.cw = max(r["w"] for r in manifest["rows"])   # 캔버스(가장 큰 프레임)
        self.ch = max(r["h"] for r in manifest["rows"])
        self._raw = {}
        for info in manifest["rows"]:
            for c in range(1, info["frames"] + 1):
                path = frame_dir / f"r{info['row']:02d}_c{c:02d}.png"
                if path.exists():
                    pm = QPixmap(str(path))
                    if not pm.isNull():
                        self._raw[(info["row"], c)] = pm
        self._pix = {}
        self._region = {}

    def clear_cache(self):
        self._pix.clear()
        self._region.clear()

    def raw(self, row, col):
        return self._raw.get((row, col)) or self._raw[(1, 1)]

    def _flipped(self, row, col, flip):
        pm = self.raw(row, col)
        return pm.transformed(QTransform().scale(-1, 1)) if flip else pm

    def pixmap(self, row, col, flip, scale, dpr):
        key = (row, col, flip, round(scale, 3), dpr)
        pm = self._pix.get(key)
        if pm is None:
            src = self._flipped(row, col, flip)
            size = QSize(max(1, round(src.width() * scale * dpr)), max(1, round(src.height() * scale * dpr)))
            pm = src.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._pix[key] = pm
        return pm

    def region(self, row, col, flip, scale):
        """캐릭터 몸통만 클릭되도록 하는 마스크(투명 영역은 클릭이 뒤로 통과)."""
        key = (row, col, flip, round(scale, 3))
        reg = self._region.get(key)
        if reg is None:
            src = self._flipped(row, col, flip)
            small = src.scaled(QSize(max(1, round(src.width() * scale)), max(1, round(src.height() * scale))),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            reg = QRegion(small.mask())
            self._region[key] = reg
        return reg

    def offset(self, row, col, scale):
        """프레임을 캔버스 '아래 중앙'에 맞춰 놓기 위한 좌표."""
        pm = self.raw(row, col)
        return QPoint(round((self.cw - pm.width()) * scale / 2), round((self.ch - pm.height()) * scale))


# ──────────────────────────────────────────────────────────────────────────────
# 키보드 입력 감지 (키 내용은 읽지 않음)
# ──────────────────────────────────────────────────────────────────────────────
class InputWatcher(QObject):
    typed = pyqtSignal()      # 키 입력이 있었음 (어떤 키인지는 알 수 없음)
    hotkey = pyqtSignal()     # Ctrl+Alt+C

    def __init__(self):
        super().__init__()
        self.backend = "none"
        self.note = ""
        self._last_emit = 0.0
        self._stops = []

    def _ping(self):
        now = time.monotonic()
        if now - self._last_emit >= 0.04:     # 초당 25회까지만 전달
            self._last_emit = now
            self.typed.emit()

    # -- 백엔드 -----------------------------------------------------------
    def _start_keyboard(self):
        import keyboard  # 윈도우: 관리자 권한 없이 동작. 맥/리눅스: root 필요

        def on_event(ev):
            if ev.event_type == "down":
                self._ping()

        keyboard.hook(on_event)
        keyboard.add_hotkey(HOTKEY_TEXT.lower(), lambda: self.hotkey.emit())
        self._stops.append(lambda: keyboard.unhook_all())

    def _start_pynput(self):
        from pynput import keyboard as pk  # 맥: 접근성 권한만 있으면 됨

        trusted = getattr(pk.Listener, "IS_TRUSTED", True)
        listener = pk.Listener(on_press=lambda _k: self._ping())
        listener.daemon = True
        listener.start()
        hot = pk.GlobalHotKeys({"<ctrl>+<alt>+c": lambda: self.hotkey.emit()})
        hot.daemon = True
        hot.start()
        self._stops += [listener.stop, hot.stop]
        if not trusted:
            self.note = "맥OS 접근성 권한이 필요합니다 (시스템 설정 → 개인정보 보호 및 보안 → 접근성)."

    def start(self):
        order = ["keyboard", "pynput"] if sys.platform.startswith("win") else ["pynput", "keyboard"]
        errors = []
        for name in order:
            try:
                (self._start_keyboard if name == "keyboard" else self._start_pynput)()
                self.backend = name
                return name
            except Exception as exc:  # 라이브러리 없음/권한 부족/디스플레이 없음 등
                errors.append(f"{name}: {exc}")
        self.note = "키보드 감지를 시작하지 못했습니다 → " + " | ".join(errors)
        return "none"

    def stop(self):
        for fn in self._stops:
            try:
                fn()
            except Exception:
                pass
        self._stops.clear()


# ──────────────────────────────────────────────────────────────────────────────
# 본체
# ──────────────────────────────────────────────────────────────────────────────
class Chiikawa(QWidget):
    def __init__(self, bank, cfg, watcher, debug=False):
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.setWindowTitle("Chiikawa")

        self.bank, self.cfg, self.watcher, self.debug = bank, cfg, watcher, debug
        self.scale = min(SCALE_MAX, max(SCALE_MIN, float(cfg["scale"])))
        self.opacity = float(cfg["opacity"])

        # 애니메이션 상태
        self.state = "idle"
        self._forced = False
        self._token = 0
        self._frames, self._idx, self._loop, self._on_end = [], 0, False, None
        self._frame = (1, 1, False)
        self._pm = None
        self._off = QPoint(0, 0)

        # 입력/활동 상태
        now = time.monotonic()
        self.last_key = -1e9
        self.last_activity = now
        self._keys = deque()
        self._cursor = QCursor.pos()
        self._sleep_since = 0.0
        self._demo_until = 0.0

        # 타이핑(FOCUS) 상태
        self._focus_key = None
        self._notice_until = 0.0
        self._focus_dir = "R"

        # 드래그
        self._press = None
        self._origin = QPoint()
        self._dragging = False

        self._apply_size()
        self.setWindowOpacity(self.opacity)
        self._place_initial()

        watcher.typed.connect(self._on_typed)
        watcher.hotkey.connect(self.toggle_visible)

        self._logic = QTimer(self)
        self._logic.timeout.connect(self._tick)
        self._logic.start(250)

        self._random_timer = QTimer(self)
        self._random_timer.setSingleShot(True)
        self._random_timer.timeout.connect(self._random_action)
        self._schedule_random()

        self._go_idle()

    # -- 유틸 -------------------------------------------------------------
    def _log(self, *a):
        if self.debug:
            print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)

    @staticmethod
    def _rand(a, b):
        return random.uniform(a, b)

    def _apply_size(self):
        self.setFixedSize(max(8, round(self.bank.cw * self.scale)), max(8, round(self.bank.ch * self.scale)))

    def _place_initial(self):
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is not None and y is not None:
            probe = QPoint(int(x) + self.width() // 2, int(y) + self.height() // 2)
            if QApplication.screenAt(probe) is not None:
                self.move(int(x), int(y))
                return
        area = QApplication.primaryScreen().availableGeometry()
        # 작업표시줄 바로 위에 앉은 느낌: 창 아래를 작업표시줄 위에 맞춘다
        self.move(area.right() - self.width() - 30, area.bottom() + 1 - self.height())

    def save(self):
        self.cfg.update(scale=round(self.scale, 3), opacity=self.opacity, x=self.x(), y=self.y())
        save_config(self.cfg)

    # -- 그리기 / 프레임 재생 ---------------------------------------------
    def _set_frame(self, row, col, flip):
        self._frame = (row, col, flip)
        dpr = self.devicePixelRatioF()
        self._pm = self.bank.pixmap(row, col, flip, self.scale, dpr)
        self._off = self.bank.offset(row, col, self.scale)
        self.setMask(self.bank.region(row, col, flip, self.scale).translated(self._off))
        self.update()

    def paintEvent(self, _e):
        if self._pm is not None:
            p = QPainter(self)
            p.drawPixmap(self._off, self._pm)

    def _play(self, frames, loop=False, on_end=None):
        """frames: [(row, col, flip, ms), ...]"""
        self._token += 1
        self._frames, self._idx, self._loop, self._on_end = frames, 0, loop, on_end
        self._show_current(self._token)

    def _show_current(self, token):
        row, col, flip, ms = self._frames[self._idx]
        self._set_frame(row, col, flip)
        QTimer.singleShot(int(ms), lambda: self._advance(token))

    def _advance(self, token):
        if token != self._token:
            return
        self._idx += 1
        if self._idx >= len(self._frames):
            if self._loop:
                self._idx = 0
            else:
                cb = self._on_end
                if cb:
                    cb()
                return
        self._show_current(token)

    # -- 대기(IDLE) ---------------------------------------------------------
    def _go_idle(self):
        self.state, self._forced = "idle", False
        self._log("→ idle")
        self._idle_step()

    def _idle_step(self):
        if self.state != "idle":
            return
        r = random.random()
        R = self._rand
        if r < 0.70:        # 멍하니 서서 눈 깜빡
            frames = [(1, 1, False, R(2000, 4200)), (1, 2, False, 70), (1, 3, False, 100), (1, 2, False, 70)]
        elif r < 0.82:      # 갸웃, 두리번
            f = random.random() < 0.5
            frames = [(1, 1, False, 600), (2, 2, f, R(900, 1300)), (2, 3, f, 700), (1, 1, False, 500)]
        elif r < 0.92:      # 눈동자 살짝살짝
            frames = [(1, 1, False, 1200), (1, 5, False, 900), (1, 6, False, 900), (1, 7, False, 900), (1, 1, False, 600)]
        else:               # 방긋
            frames = [(1, 1, False, 600), (5, 3, False, 1300), (1, 1, False, 400)]
        self._play(frames, on_end=self._idle_step)

    # -- 타이핑(FOCUS) ------------------------------------------------------
    def _kps(self):
        now = time.monotonic()
        while self._keys and now - self._keys[0] > 2.0:
            self._keys.popleft()
        return len(self._keys) / 2.0

    def _type_level(self):
        """0 = 잠깐 손을 멈춤, 1 = 보통 타이핑, 2 = 열심히 두드리는 중."""
        if time.monotonic() - self.last_key > 1.4:
            return 0
        return 2 if self._kps() >= 5.0 else 1

    def _gaze_vector(self):
        """캐릭터에서 '사용자의 작업 방향'(마우스 커서)까지의 벡터. 너무 가까우면 화면 중앙."""
        c = self.geometry().center()
        p = QCursor.pos()
        dx, dy = p.x() - c.x(), p.y() - c.y()
        if math.hypot(dx, dy) < 120 * max(self.scale, 0.5):
            scr = QApplication.screenAt(c) or QApplication.primaryScreen()
            m = scr.geometry().center()
            dx, dy = m.x() - c.x(), m.y() - c.y()
        return dx, dy

    def _build_notice(self):
        """타이핑을 알아채고 사용자 쪽을 쳐다보는 짧은 동작 (커서가 위쪽이면 3행으로 앞으로 내다봄)."""
        R = self._rand
        dx, dy = self._gaze_vector()
        d = "R" if dx > 0 else "L"
        if dy < -80 and dy < -abs(dx):
            flip = d == "R"                     # 3행 원본은 왼쪽을 봄
            return [(3, c, flip, 80) for c in (1, 2, 3, 4, 5)] + [(3, 5, flip, R(350, 600))]
        if d == "R":
            return [(2, c, False, R(420, 650)) for c in random.sample([2, 3, 5, 6], 2)]
        return [(2, c, False, R(420, 650)) for c in (4, 7)]

    def _build_typing(self, level):
        """키보드 치는 동작 한 토막(약 1초). 끝나면 다시 이어서 만들어 계속 자연스럽게 움직임."""
        R = self._rand
        if level == 0:       # 생각하는 중: 손 멈추고 살짝 깜빡
            return [(TYPE_A, 1, False, R(700, 1200)), (TYPE_A, 2, False, R(150, 300)),
                    (TYPE_A, 1, False, R(500, 900))]
        frames, prev = [], None
        if level == 1:       # 보통: 손이 내려갔다 올라가며 두드림
            low, high = [1, 2, 3], [4, 5, 6]
            for i in range(random.randint(7, 11)):
                col = random.choice([c for c in (high if i % 2 else low) if c != prev])
                frames.append((TYPE_A, col, False, R(85, 150)))
                prev = col
            if random.random() < 0.25:               # 가끔 숨 고르기
                frames.append((TYPE_A, random.choice([1, 2]), False, R(250, 500)))
            return frames
        pool = [(TYPE_B, 1), (TYPE_B, 2), (TYPE_A, 4), (TYPE_A, 5), (TYPE_A, 6), (TYPE_B, 2)]
        for _ in range(random.randint(8, 12)):       # 열심히: 몸을 앞으로 숙이며 빠르게
            row, col = random.choice([p for p in pool if p != prev])
            frames.append((row, col, False, R(60, 100)))
            prev = (row, col)
        return frames

    def _focus_key_now(self):
        if time.monotonic() < self._notice_until:
            return ("notice",)
        return ("type", self._type_level())

    def _enter_focus(self):
        self.state, self._forced = "focus", False
        self._notice_until = time.monotonic() + (self._rand(1.0, 1.6) if self.cfg["notice_look"] else 0.0)
        self._focus_key = None
        self._log("→ focus")
        self._play_focus()

    def _play_focus(self):
        if self.state != "focus":
            return
        key = self._focus_key_now()
        self._focus_key = key
        self._log("focus", key)
        if key[0] == "notice":
            self._play(self._build_notice(), on_end=self._play_focus)
        else:
            self._play(self._build_typing(key[1]), on_end=self._play_focus)

    def _exit_focus(self):
        """타이핑이 끝나면 '후…' 하고 한숨 돌린 뒤 대기로."""
        self.state, self._forced = "idle", False
        self._log("→ idle (타이핑 끝)")
        self._play([(TYPE_A, 1, False, 350), (TYPE_B, 5, False, 800)], on_end=self._go_idle)

    # -- 행동(ACTION) -------------------------------------------------------
    def play_action(self, name, forced=True):
        spec = ACTIONS[name]
        self.state, self._forced = "action", forced
        self._log("→ action", name, "(forced)" if forced else "")
        frames = [(spec["row"], c, False, spec["ms"]) for c in spec["cols"]]
        frames[-1] = (frames[-1][0], frames[-1][1], False, 300)
        self._play(frames, on_end=self._go_idle)

    def _schedule_random(self):
        lo, hi = float(self.cfg["random_min"]), float(self.cfg["random_max"])
        self._random_timer.start(int(self._rand(lo, max(lo, hi)) * 1000))

    def _random_action(self):
        if self.state == "idle":
            names = list(RANDOM_WEIGHTS)
            name = random.choices(names, weights=[RANDOM_WEIGHTS[n] for n in names])[0]
            self.play_action(name, forced=False)
            self._schedule_random()
        else:                                   # 바쁠 땐 잠시 뒤에 다시
            self._random_timer.start(8000)

    # -- 낮잠(SLEEP) --------------------------------------------------------
    def _enter_sleep(self, forced=False):
        self.state, self._forced = "sleep", False
        self._sleep_since = time.monotonic() + (1.5 if forced else 0.0)
        self._log("→ sleep")
        down = [(3, 5, False, 200), (3, 6, False, 350), (3, 7, False, 450),
                (4, 1, False, 600), (4, 2, False, 700), (4, 3, False, 800)]
        loop = [(4, 3, False, 1500), (4, 4, False, 1500)]
        self._play(down, on_end=lambda: self._play(loop, loop=True))

    def _wake(self):
        self._log("wake")
        up = [(4, 2, False, 180), (3, 7, False, 140), (3, 6, False, 140), (3, 5, False, 140), (3, 3, False, 100)]
        self.state = "idle"
        self._play(up, on_end=self._go_idle)

    # -- 입력/주기 로직 -----------------------------------------------------
    def _register_key(self):
        now = time.monotonic()
        self.last_key = now
        self.last_activity = now
        self._keys.append(now)

    def _on_typed(self):
        if self.cfg["keyboard"]:
            self._register_key()

    def demo_typing(self, seconds=7.0):
        """우클릭 메뉴 '키보드 치기(미리보기)': 실제 키 입력 없이 타이핑 동작을 보여줌."""
        end = time.monotonic() + seconds
        self._demo_until = end

        def beat():
            if time.monotonic() < end:
                self._register_key()
                QTimer.singleShot(random.randint(90, 200), beat)
        beat()

    def _typing(self):
        return (time.monotonic() - self.last_key) < float(self.cfg["focus_timeout"])

    def _tick(self):
        now = time.monotonic()
        cur = QCursor.pos()
        if (cur - self._cursor).manhattanLength() > 3:
            self._cursor = cur
            self.last_activity = now
        typing = self._typing()
        st = self.state

        if st == "sleep":
            if self.last_activity > self._sleep_since + 0.3:
                self._wake()
            return
        if st == "idle" or (st == "action" and not self._forced):
            if typing:
                self._enter_focus()
                return
        if st == "focus":
            if not typing:
                self._exit_focus()
                return
            if self._focus_key_now() != self._focus_key:
                self._play_focus()
        elif st == "idle":
            if now - self.last_activity >= float(self.cfg["sleep_after"]):
                self._enter_sleep()

    # -- 클릭 반응 ----------------------------------------------------------
    def _react_click(self):
        self.last_activity = time.monotonic()
        if self.state == "sleep":
            self._wake()
            return
        self.play_action(random.choice(["sweat", "wave", "cheer"]), forced=True)

    # -- 마우스 이벤트 ------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.globalPos()
            self._origin = self.pos()
            self._dragging = False
        elif e.button() == Qt.RightButton:
            self._show_menu()

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        delta = e.globalPos() - self._press
        if not self._dragging and delta.manhattanLength() > 5:
            self._dragging = True
            self.state, self._forced = "drag", True
            self._play([(7, 1, False, 1000)], loop=True)
        if self._dragging:
            self.move(self._origin + delta)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        was_drag = self._dragging
        self._press, self._dragging = None, False
        if was_drag:
            self._snap_to_edges()
            self.save()
            self.last_activity = time.monotonic()
            self._go_idle()
        else:
            self._react_click()

    def _snap_to_edges(self, margin=24):
        scr = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        a = scr.availableGeometry()
        g = self.geometry()
        x, y = g.x(), g.y()
        if abs(g.left() - a.left()) < margin:
            x = a.left()
        elif abs(a.right() - g.right()) < margin:
            x = a.right() + 1 - g.width()
        if abs(a.bottom() - g.bottom()) < margin:
            y = a.bottom() + 1 - g.height()
        elif abs(g.top() - a.top()) < margin:
            y = a.top()
        self.move(x, y)

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.set_scale(self.scale * (1.1 ** steps))
        e.accept()

    def enterEvent(self, _e):
        self.setWindowOpacity(1.0)

    def leaveEvent(self, _e):
        self.setWindowOpacity(self.opacity)

    # -- 설정 변경 ----------------------------------------------------------
    def set_scale(self, s):
        s = min(SCALE_MAX, max(SCALE_MIN, s))
        if abs(s - self.scale) < 1e-4:
            return
        g = self.geometry()
        cx, bottom = g.center().x(), g.bottom()          # 아래 중앙 기준으로 크기 변경
        self.scale = s
        self.bank.clear_cache()
        self._apply_size()
        self.move(cx - self.width() // 2, bottom + 1 - self.height())
        self._set_frame(*self._frame)
        self.save()

    def set_opacity(self, v):
        self.opacity = v
        self.setWindowOpacity(v)
        self.save()

    def toggle_visible(self):
        self.hide() if self.isVisible() else self.show()

    # -- 우클릭 메뉴 --------------------------------------------------------
    def _show_menu(self):
        m = QMenu()
        m.addAction("키보드 치기 (미리보기)").triggered.connect(lambda: self.demo_typing())
        m.addSeparator()
        for name, spec in ACTIONS.items():
            m.addAction(spec["label"]).triggered.connect(lambda _=False, n=name: self.play_action(n, forced=True))
        m.addAction("낮잠 자기").triggered.connect(lambda: self._enter_sleep(forced=True))
        m.addSeparator()

        size_menu = m.addMenu("크기  (마우스 휠로도 조절)")
        for label, s in SIZE_PRESETS:
            a = size_menu.addAction(f"{label}  ({s:g}배)")
            a.setCheckable(True)
            a.setChecked(abs(self.scale - s) < 0.02)
            a.triggered.connect(lambda _=False, v=s: self.set_scale(v))

        op_menu = m.addMenu("투명도")
        group = QActionGroup(op_menu)
        for pct in (40, 55, 70, 85, 100):
            a = op_menu.addAction(f"{pct}%")
            a.setCheckable(True)
            a.setChecked(abs(self.opacity * 100 - pct) < 3)
            group.addAction(a)
            a.triggered.connect(lambda _=False, v=pct / 100: self.set_opacity(v))

        for key, label in (("keyboard", "키보드 입력 감지"), ("notice_look", "타이핑 시작 때 먼저 쳐다보기")):
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(bool(self.cfg[key]))
            a.triggered.connect(lambda checked, k=key: self._toggle_cfg(k, checked))

        m.addSeparator()
        m.addAction(f"숨기기 ({HOTKEY_TEXT}로 다시 표시)").triggered.connect(self.toggle_visible)
        m.addAction("프로그램 종료").triggered.connect(self.quit_app)
        m.exec_(QCursor.pos())

    def _toggle_cfg(self, key, value):
        self.cfg[key] = bool(value)
        save_config(self.cfg)

    def quit_app(self):
        self.save()
        self.watcher.stop()
        QApplication.quit()


# ──────────────────────────────────────────────────────────────────────────────
def ensure_frames():
    if (FRAME_DIR / "manifest.json").exists():
        return True
    print("frames/ 폴더가 없어 sprite_sheet*.png 에서 프레임을 만듭니다...")
    try:
        import prepare_sprites
    except ImportError as exc:
        print("prepare_sprites 를 불러올 수 없습니다:", exc, "\n→ pip install pillow numpy")
        return False
    return prepare_sprites.main() == 0


def build_tray(app, pet, bank):
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    icon = QIcon(bank.raw(1, 1).scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip("치이카와 응원 위젯")
    menu = QMenu()
    menu.addAction("보이기 / 숨기기").triggered.connect(pet.toggle_visible)
    menu.addAction("종료").triggered.connect(pet.quit_app)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: pet.toggle_visible() if reason == QSystemTrayIcon.Trigger else None)
    tray.show()
    return tray


def main():
    ap = argparse.ArgumentParser(description="치이카와 데스크톱 응원 위젯")
    ap.add_argument("--no-keyboard", action="store_true", help="전역 키보드 감지를 시작하지 않음")
    ap.add_argument("--reset", action="store_true", help="저장된 설정(위치·크기)을 초기화")
    ap.add_argument("--debug", action="store_true", help="상태 전환 로그 출력")
    args = ap.parse_args()

    if hasattr(Qt, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    if not ensure_frames():
        return 1
    bank = SpriteBank(FRAME_DIR)
    cfg = load_config(reset=args.reset)

    watcher = InputWatcher()
    if not args.no_keyboard:
        backend = watcher.start()
        print(f"[키보드 감지] 백엔드: {backend}")
        if watcher.note:
            print("[안내]", watcher.note)

    pet = Chiikawa(bank, cfg, watcher, debug=args.debug)
    pet.show()
    tray = build_tray(app, pet, bank)  # noqa: F841  (참조 유지)
    code = app.exec_()
    watcher.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
