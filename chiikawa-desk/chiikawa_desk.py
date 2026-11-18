#!/usr/bin/env python3
"""치이카와 데스크톱 응원 위젯 (PyQt5)

바탕화면 위에 항상 떠 있는 투명 배경 치이카와가 내가 일하는 모습을 지켜보며 응원해 줍니다.

  * 키보드를 치면 → 사용자가 있는 쪽(마우스 커서 방향)을 뚫어지게 쳐다봄
  * 입력이 4초 멈추면 → 다시 멍하니 깜빡임, 30~60초마다 랜덤 행동
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
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QPoint, QRect, QSize, Qt, QObject, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QIcon, QPainter, QPainterPath, QPen,
    QPixmap, QRegion, QTransform,
)
from PyQt5.QtWidgets import (
    QAction, QActionGroup, QApplication, QMenu, QSystemTrayIcon, QWidget,
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
    "bubbles": True,        # 말풍선
    "reminders": True,      # 휴식·점심·퇴근 알림
    "focus_timeout": 4.0,   # 입력이 이 시간(초) 멈추면 쳐다보기 종료 (3~5초 권장)
    "random_min": 30,       # 랜덤 행동 간격(초)
    "random_max": 60,
    "sleep_after": 300,     # 아무 활동이 없으면 낮잠(초)
    "break_after": 3000,    # 연속 작업 알림(초) = 50분
}

SCALE_MIN, SCALE_MAX = 0.2, 3.0

# 행동 정의: 스프라이트 행(row, 1부터), 재생할 열 순서, 프레임당 ms, 말풍선 문구
ACTIONS = {
    "cheer":  dict(label="응원하기",     row=5,  ms=130, cols=[1, 2, 3, 4, 5, 6, 4, 5, 6, 5, 4, 3, 2, 1],
                   lines=["화이팅!", "힘내요, 할 수 있어요!", "오늘도 빛나요 ♪"]),
    "wave":   dict(label="손 흔들기",    row=6,  ms=120, cols=[1, 2, 3, 4, 5, 6, 3, 4, 5, 6, 3, 4, 5, 6, 2, 1],
                   lines=["안녕~!", "수고하고 있어요!", "저 여기 있어요~"]),
    "hearts": dict(label="하트 날리기",  row=11, ms=150, cols=[1, 2, 3, 4, 5, 6, 5, 6, 5, 4, 3, 2, 1],
                   lines=["수고했어요 ♥", "항상 응원해요 ♥"]),
    "cry":    dict(label="울먹이기",     row=9,  ms=150, cols=[1, 2, 3, 4, 5, 6, 5, 6, 5, 6, 4, 3, 2, 1],
                   lines=["흑흑...", "많이 힘들었죠...?"]),
    "angry":  dict(label="삐지기",       row=8,  ms=140, cols=[1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1],
                   lines=["흥! 삐졌어요", "쉬엄쉬엄 해요, 흥!"]),
    "dizzy":  dict(label="어지러워하기", row=10, ms=140, cols=[1, 2, 3, 4, 5, 6, 1, 2, 3, 4, 5, 6, 3, 2, 1],
                   lines=["어질어질~", "빙글빙글..."]),
    "sweat":  dict(label="깜짝 놀라기",  row=7,  ms=140, cols=[1, 2, 3, 4, 5, 6, 5, 4, 3, 2, 1],
                   lines=["앗...!", "으앗, 깜짝이야!"]),
}
RANDOM_WEIGHTS = {"cheer": 3, "wave": 3, "hearts": 2, "cry": 1, "angry": 1, "dizzy": 1, "sweat": 1}

CHEER_LINES = [
    "집중하고 있네요! 멋져요", "조금만 더 힘내요!", "오늘도 화이팅!", "잘하고 있어요~",
    "마감 전에 다 끝낼 수 있어요!", "저장(Ctrl+S) 잊지 마세요!", "물 한 모금 어때요?",
]


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
        self.counts = {r["row"]: r["frames"] for r in manifest["rows"]}
        self.cw = max(r["w"] for r in manifest["rows"])   # 캔버스(가장 큰 프레임)
        self.ch = max(r["h"] for r in manifest["rows"])
        self._raw = {}
        for info in manifest["rows"]:
            for c in range(1, info["frames"] + 1):
                pm = QPixmap(str(frame_dir / f"r{info['row']:02d}_c{c:02d}.png"))
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
# 말풍선
# ──────────────────────────────────────────────────────────────────────────────
class Bubble(QWidget):
    TAIL = 9

    def __init__(self):
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if hasattr(Qt, "WindowTransparentForInput"):
            flags |= Qt.WindowTransparentForInput
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self._text = ""
        self._below = False
        self._font = QFont()
        self._font.setPointSize(10)
        self._font.setBold(True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def say(self, text, anchor, ms=3200):
        self._text = text
        fm = QFontMetrics(self._font)
        rect = fm.boundingRect(QRect(0, 0, 220, 400), Qt.TextWordWrap, text)
        self.resize(rect.width() + 28, rect.height() + 18 + self.TAIL)
        self.reposition(anchor)
        self.show()
        self.raise_()
        self._timer.start(ms)

    def reposition(self, anchor):
        if not self.isVisible() and not self._text:
            return
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = anchor.center().x() - self.width() // 2
        y = anchor.top() - self.height() + 4
        self._below = y < area.top()
        if self._below:
            y = anchor.bottom() - 4
        x = max(area.left() + 4, min(x, area.right() - self.width() - 4))
        self._tail_x = anchor.center().x() - x
        self._tail_x = max(16, min(self.width() - 16, self._tail_x))
        self.move(x, y)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        tail = self.TAIL
        body = QRect(1, 1 + (tail if self._below else 0), self.width() - 2, self.height() - tail - 2)
        path = QPainterPath()
        path.addRoundedRect(body.x(), body.y(), body.width(), body.height(), 12, 12)
        tx = getattr(self, "_tail_x", self.width() // 2)
        tri = QPainterPath()
        if self._below:
            tri.moveTo(tx - 7, body.top() + 1)
            tri.lineTo(tx, 1)
            tri.lineTo(tx + 7, body.top() + 1)
        else:
            tri.moveTo(tx - 7, body.bottom() - 1)
            tri.lineTo(tx, self.height() - 1)
            tri.lineTo(tx + 7, body.bottom() - 1)
        path = path.united(tri)
        p.setPen(QPen(QColor("#5b4543"), 2))
        p.setBrush(QColor("#fffaf6"))
        p.drawPath(path)
        p.setPen(QColor("#4a3a38"))
        p.setFont(self._font)
        p.drawText(body.adjusted(8, 4, -8, -4), Qt.AlignCenter | Qt.TextWordWrap, self._text)


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
        self.bubble = Bubble()

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
        self._session_start = now
        self._break_notified = False
        self._cursor = QCursor.pos()
        self._fired = set()
        self._next_cheer = now + 90
        self._sleep_since = 0.0

        # 포커스(쳐다보기) 상태
        self._focus_key = None
        self._focus_prev_mode = None
        self._focus_dir = "R"
        self._variant_next = now + 3
        self._variant_until = 0.0

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
        self.setFixedSize(round(self.bank.cw * self.scale), round(self.bank.ch * self.scale))

    def _place_initial(self):
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is not None and y is not None:
            probe = QPoint(int(x) + self.width() // 2, int(y) + self.height() // 2)
            if QApplication.screenAt(probe) is not None:
                self.move(int(x), int(y))
                return
        area = QApplication.primaryScreen().availableGeometry()
        # 화면 아래 모서리에서 빼꼼 올라온 느낌: 창 아래를 작업표시줄 위에 맞춘다
        self.move(area.right() - self.width() - 30, area.bottom() + 1 - self.height())

    def anchor_rect(self):
        g = self.geometry()
        return QRect(g.x(), g.y() + int(g.height() * 0.1), g.width(), int(g.height() * 0.9))

    def say(self, text, ms=3200):
        if self.cfg["bubbles"] and self.isVisible():
            self.bubble.say(text, self.anchor_rect(), ms)

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

    # -- 쳐다보기(FOCUS) ----------------------------------------------------
    def _kps(self):
        now = time.monotonic()
        while self._keys and now - self._keys[0] > 2.0:
            self._keys.popleft()
        return len(self._keys) / 2.0

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

    def _compute_focus(self):
        dx, dy = self._gaze_vector()
        if abs(dx) > 30:                       # 방향 떨림 방지(히스테리시스)
            self._focus_dir = "R" if dx > 0 else "L"
        mode = "lean" if (dy < -80 and dy < -abs(dx)) else "look"
        now = time.monotonic()
        if now >= self._variant_next:           # 가끔 꼬지락, 눈 동그랗게 뜨기
            self._variant_next = now + self._rand(3, 6)
            if random.random() < 0.55:
                self._variant_until = now + self._rand(1.2, 2.4)
        if now < self._variant_until and self._kps() >= 2.0:
            mode = "look" if mode == "lean" else "lean"
        return mode, self._focus_dir

    def _build_focus(self, mode, d, ramp):
        R = self._rand
        if mode == "lean":                      # 3행: 앞으로 쑥 내다보기 (원본이 왼쪽을 봄)
            flip = d == "R"
            frames = []
            if ramp:
                frames += [(3, c, flip, 80) for c in (1, 2, 3, 4, 5)]
            frames += [(3, 5, flip, R(600, 1100)), (3, 4, flip, 150), (3, 5, flip, R(400, 800)), (3, 4, flip, 150)]
            return frames
        if d == "R":                            # 2행: 오른쪽 보기 (2·3·5·6열)
            cols = random.sample([2, 3, 5, 6], 3)
            return [(2, c, False, R(650, 1300)) for c in cols]
        cols = [4, 7, random.choice([4, 7])]    # 2행: 왼쪽 보기 (4·7열)
        return [(2, c, False, R(650, 1300)) for c in cols]

    def _enter_focus(self):
        self.state, self._forced = "focus", False
        self._focus_key, self._focus_prev_mode = None, None
        self._next_cheer = time.monotonic() + self._rand(60, 120)
        self._log("→ focus")
        self._play_focus()

    def _play_focus(self):
        if self.state != "focus":
            return
        mode, d = self._compute_focus()
        ramp = mode == "lean" and self._focus_prev_mode != "lean"
        self._focus_key, self._focus_prev_mode = (mode, d), mode
        self._log("focus", mode, d)
        self._play(self._build_focus(mode, d, ramp), on_end=self._play_focus)

    # -- 행동(ACTION) -------------------------------------------------------
    def play_action(self, name, forced=True, say=True):
        spec = ACTIONS[name]
        self.state, self._forced = "action", forced
        self._log("→ action", name, "(forced)" if forced else "")
        frames = [(spec["row"], c, False, spec["ms"]) for c in spec["cols"]]
        frames[-1] = (frames[-1][0], frames[-1][1], False, 300)
        self._play(frames, on_end=self._go_idle)
        if say and spec["lines"]:
            self.say(random.choice(spec["lines"]))

    def _schedule_random(self):
        lo, hi = float(self.cfg["random_min"]), float(self.cfg["random_max"])
        self._random_timer.start(int(self._rand(lo, max(lo, hi)) * 1000))

    def _random_action(self):
        if self.state == "idle":
            names = list(RANDOM_WEIGHTS)
            name = random.choices(names, weights=[RANDOM_WEIGHTS[n] for n in names])[0]
            self.play_action(name, forced=False, say=random.random() < 0.6)
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
        self.say("쿨쿨... zZ", 2500)

    def _wake(self):
        self._log("wake")
        up = [(4, 2, False, 180), (3, 7, False, 140), (3, 6, False, 140), (3, 5, False, 140), (3, 3, False, 100)]
        self.state = "idle"
        self._play(up, on_end=self._go_idle)

    # -- 입력/주기 로직 -----------------------------------------------------
    def _on_typed(self):
        if not self.cfg["keyboard"]:
            return
        now = time.monotonic()
        if now - self.last_key > 300:           # 5분 이상 쉬었다면 새 작업 세션
            self._session_start, self._break_notified = now, False
        self.last_key = now
        self.last_activity = now
        self._keys.append(now)

    def _typing(self):
        return self.cfg["keyboard"] and (time.monotonic() - self.last_key) < float(self.cfg["focus_timeout"])

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
        if st in ("idle",) or (st == "action" and not self._forced):
            if typing:
                self._enter_focus()
                return
        if st == "focus":
            if not typing:
                self._go_idle()
                return
            if self._compute_focus() != self._focus_key:
                self._play_focus()
            if now >= self._next_cheer:
                self._next_cheer = now + self._rand(120, 240)
                self.say(random.choice(CHEER_LINES))
        elif st == "idle":
            if now - self.last_activity >= float(self.cfg["sleep_after"]):
                self._enter_sleep()
                return

        self._check_reminders(now, typing)

    def _check_reminders(self, now, typing):
        if not self.cfg["reminders"]:
            return
        if typing and not self._break_notified and now - self._session_start >= float(self.cfg["break_after"]):
            self._break_notified = True
            self.play_action("wave", forced=True, say=False)
            self.say("50분째 작업 중이에요! 잠깐 스트레칭 해요~", 6000)
            return
        t = datetime.now()
        today = t.date().isoformat()
        for hour, tag, action, text in ((12, "lunch", "cheer", "점심시간이에요! 맛있게 드세요~"),
                                        (18, "leave", "hearts", "오늘도 수고하셨어요! ♥")):
            key = (today, tag)
            if t.hour == hour and t.minute < 10 and key not in self._fired and self.state in ("idle", "focus", "action"):
                self._fired.add(key)
                self.play_action(action, forced=True, say=False)
                self.say(text, 6000)

    # -- 클릭 반응 ----------------------------------------------------------
    def _react_click(self):
        self.last_activity = time.monotonic()
        if self.state == "sleep":
            self._wake()
            self.say("으앗, 깜짝이야...!")
            return
        name = random.choice(["sweat", "wave", "cheer"])
        self.play_action(name, forced=True, say=True)

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
            self._prev_state = self.state
            self.state, self._forced = "drag", True
            self._play([(7, 1, False, 1000)], loop=True)
        if self._dragging:
            self.move(self._origin + delta)
            self.bubble.reposition(self.anchor_rect())

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
            self.set_scale(self.scale * (1.08 ** steps))
        e.accept()

    def enterEvent(self, _e):
        self.setWindowOpacity(1.0)

    def leaveEvent(self, _e):
        self.setWindowOpacity(self.opacity)

    def moveEvent(self, _e):
        self.bubble.reposition(self.anchor_rect())

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
        if self.isVisible():
            self.bubble.hide()
            self.hide()
        else:
            self.show()

    # -- 우클릭 메뉴 --------------------------------------------------------
    def _show_menu(self):
        m = QMenu()
        for name, spec in ACTIONS.items():
            if name == "sweat":
                continue
            act = m.addAction(spec["label"])
            act.triggered.connect(lambda _=False, n=name: self.play_action(n, forced=True))
        m.addAction("깜짝 놀라기").triggered.connect(lambda: self.play_action("sweat", forced=True))
        m.addAction("낮잠 자기").triggered.connect(lambda: self._enter_sleep(forced=True))
        m.addSeparator()

        size_menu = m.addMenu("크기  (마우스 휠로도 조절)")
        for label, s in (("아주 작게", 0.25), ("작게", 0.35), ("보통", 0.5), ("크게", 0.8), ("아주 크게", 1.2)):
            a = size_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.scale - s) < 0.03)
            a.triggered.connect(lambda _=False, v=s: self.set_scale(v))

        op_menu = m.addMenu("투명도")
        group = QActionGroup(op_menu)
        for pct in (40, 55, 70, 85, 100):
            a = op_menu.addAction(f"{pct}%")
            a.setCheckable(True)
            a.setChecked(abs(self.opacity * 100 - pct) < 3)
            group.addAction(a)
            a.triggered.connect(lambda _=False, v=pct / 100: self.set_opacity(v))

        for key, label in (("keyboard", "키보드 입력 감지"), ("bubbles", "말풍선"), ("reminders", "휴식·점심·퇴근 알림")):
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
        if key == "bubbles" and not value:
            self.bubble.hide()

    def quit_app(self):
        self.save()
        self.watcher.stop()
        self.bubble.hide()
        QApplication.quit()


# ──────────────────────────────────────────────────────────────────────────────
def ensure_frames():
    if (FRAME_DIR / "manifest.json").exists():
        return True
    print("frames/ 폴더가 없어 sprite_sheet.png 에서 프레임을 만듭니다...")
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
    if watcher.note:
        QTimer.singleShot(800, lambda: pet.say("키보드 감지 권한을 확인해 주세요 (콘솔 안내 참고)", 6000))
    elif cfg["bubbles"]:
        QTimer.singleShot(800, lambda: pet.say("오늘도 같이 힘내요!", 2500))
    code = app.exec_()
    watcher.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())
