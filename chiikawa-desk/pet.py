"""캐릭터 한 마리 = 투명 창 하나.

* 모드 3가지
    idle   : 쉬는 동안 쉬지 않고 다른 동작을 이어감(IdleActor) — 다른 캐릭터가 하는 동작은 피한다
    type   : 키보드를 두드림(TypingActor) — 캐릭터마다 박자·컷 순서가 다름
    static : 포즈 한 장(집중/휴식/응원) + 작은 움직임
* 모든 움직임은 '그리기 변환'으로 처리하고, 클릭 영역(마스크)은 컷이 바뀔 때만 갱신한다.
* 끌어서 옮길 수 있다(Shift 를 누르고 끌면 모두 함께).
"""
import json
import math
import random
from pathlib import Path

from PyQt5.QtCore import QPoint, QPointF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap, QRegion, QTransform
from PyQt5.QtWidgets import QWidget

import behaviors as bh

POSES = ("base", "focus", "rest", "cheer")
CHAR_LABEL = {"chiikawa": "치이카와", "hachiware": "하치와레", "usagi": "우사기"}
CHARS = ("chiikawa", "hachiware", "usagi")

SCALE_MIN, SCALE_MAX = 0.08, 3.0
SIZE_PRESETS = [("초소형", 0.12), ("아주 작게", 0.2), ("작게", 0.3), ("조금 작게", 0.4),
                ("보통", 0.5), ("크게", 0.8), ("아주 크게", 1.1)]


class PoseBank:
    """frames/poses/*.png 를 읽어 (크기별) 캐시해 두는 저장소. 컷은 '이름'으로 찾는다."""

    def __init__(self, pose_dir):
        pose_dir = Path(pose_dir)
        meta = json.loads((pose_dir / "manifest.json").read_text(encoding="utf-8"))
        self.cw, self.ch = meta["canvas"]
        self._top = {k: v["bbox"][1] for k, v in meta.get("poses", {}).items()}   # 컷별 머리(귀) 꼭대기 y
        self.typing = {c: [(t["name"], bool(t["busy"])) for t in v] for c, v in meta.get("typing", {}).items()}
        self.idle = meta.get("idle", {})
        self._raw = {}
        for name in meta.get("poses", {}):
            pm = QPixmap(str(pose_dir / f"{name}.png"))
            if not pm.isNull():
                self._raw[name] = pm
        self.names = set(self._raw)
        self._pix, self._reg = {}, {}

    def has_char(self, ch):
        return all(f"{ch}_{p}" in self.names for p in POSES)

    def raw(self, name):
        return self._raw[name]

    def head_top(self, name):
        return self._top.get(name, 0)

    def clear_cache(self):
        self._pix.clear()
        self._reg.clear()

    def pixmap(self, name, scale, dpr):
        key = (name, round(scale, 3), dpr)
        pm = self._pix.get(key)
        if pm is None:
            src = self._raw[name]
            size = QSize(max(1, round(src.width() * scale * dpr)), max(1, round(src.height() * scale * dpr)))
            pm = src.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._pix[key] = pm
        return pm

    def region(self, name, scale):
        key = (name, round(scale, 3))
        reg = self._reg.get(key)
        if reg is None:
            src = self._raw[name]
            small = src.scaled(QSize(max(1, round(src.width() * scale)), max(1, round(src.height() * scale))),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            reg = QRegion(small.mask())
            self._reg[key] = reg
        return reg


class Pet(QWidget):
    clicked = pyqtSignal(object)           # 좌클릭(끌지 않음)
    context_requested = pyqtSignal(object)
    moved = pyqtSignal(object)
    drag_ended = pyqtSignal(object)
    group_step = pyqtSignal(object, object)          # (펫, 끈 만큼) — Shift+끌기: 나머지도 같이 옮김
    wheel_scaled = pyqtSignal(object, float, bool)   # (펫, 배율 변화, 전체 적용 여부)

    def __init__(self, char, bank, scale=0.5, opacity=0.85, on_top=True, seed=None, now=0.0):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.char, self.bank = char, bank
        self.rng = random.Random(seed if seed is not None else random.random())
        self.scale = min(SCALE_MAX, max(SCALE_MIN, scale))
        self.opacity = opacity
        self.mode = "idle"
        self.pose = "idle"                 # 시험·표시용 꼬리표: idle / type / base / focus / rest / cheer
        self.frame = f"{char}_base"
        self.intensity = 0.0
        self.peers = lambda: set()         # 다른 캐릭터가 지금 하는 동작 이름들
        self._idle = bh.IdleActor(char, bank.names, self.rng, now=now)
        self._typer = None
        self._static_pose = "base"
        self._extra = {}
        self._phase = self.rng.uniform(0, 6.28)
        self._phase2 = self.rng.uniform(0, 6.28)
        self._t = now
        self._hop = None                   # (시작 시각, 높이 비율, 횟수, 한 번 뛰는 시간)
        self._hop_pending = False
        self._nod_t0 = None
        self._nod_pending = False
        self._hop_height = self.rng.uniform(0.03, 0.045)
        self._motion = (0.0, 0.0, 0.0)     # (세로 이동 px, 기울기°, 가로 이동 px)
        self._press = None
        self._last = QPoint()
        self._dragging = False
        self._apply_size()
        self.setWindowOpacity(self.opacity)

    # -- 크기·마스크 --------------------------------------------------------
    def _geom(self):
        cw, ch = self.bank.cw * self.scale, self.bank.ch * self.scale
        return cw, ch, max(3.0, cw * 0.08), max(4.0, ch * 0.10)      # 캔버스 w/h, 좌우 여백, 위 여백

    def _apply_size(self):
        cw, ch, padx, pady = self._geom()
        self.setFixedSize(int(round(cw + 2 * padx)), int(round(ch + pady)))
        self._refresh_mask()
        self.update()

    def _refresh_mask(self):
        cw, ch, padx, pady = self._geom()
        reg = self.bank.region(self.frame, self.scale).translated(int(padx), int(pady))
        up, side = int(pady * 0.9), int(padx * 0.6)
        reg = reg.united(reg.translated(0, -up)).united(reg.translated(-side, 0)).united(reg.translated(side, 0))
        self.setMask(reg)

    def set_scale(self, s):
        s = min(SCALE_MAX, max(SCALE_MIN, s))
        if abs(s - self.scale) < 1e-4:
            return
        g = self.geometry()
        cx, bottom = g.center().x(), g.bottom()                      # 아래 중앙 기준으로 크기 변경
        self.scale = s
        self._apply_size()
        self.move(cx - self.width() // 2, bottom + 1 - self.height())

    def set_opacity(self, v):
        self.opacity = v
        self.setWindowOpacity(1.0 if self.underMouse() else v)

    # -- 모드 ---------------------------------------------------------------
    def _set_frame(self, name):
        if name != self.frame and name in self.bank.names:
            self.frame = name
            self._refresh_mask()
            self.update()

    def set_idle(self):
        if self.mode != "idle":
            self.mode, self.pose = "idle", "idle"
            self._idle.current = None                    # 막 쉬기 시작: 곧바로 다른 동작으로
            self._idle._rest_until = self._t + self.rng.uniform(0.1, 1.2)

    def set_typing(self, intensity):
        self.intensity = intensity
        if self.mode != "type":
            self.mode, self.pose = "type", "type"
            frames = self.bank.typing.get(self.char) or []
            self._typer = bh.TypingActor(self.char, frames, random.Random(self.rng.random()), now=self._t) if frames else None
            if self._typer is None:                      # 키보드 컷이 없으면 집중 포즈로 대신
                self.set_static("focus", intensity)

    def set_static(self, pose, intensity=0.0):
        self.intensity = intensity
        if self.mode != "static" or self._static_pose != pose:
            self.mode, self.pose, self._static_pose = "static", pose, pose
            self._set_frame(f"{self.char}_{pose}")

    # -- 움직임 -------------------------------------------------------------
    def hop(self):
        self._hop_pending = True          # 시작 시각은 다음 틱의 시각을 기준으로 잡는다(시계를 하나로 통일)

    def nod(self):
        self._nod_pending = True

    def busy(self):
        return (self._hop is not None or self._nod_t0 is not None or self._hop_pending or self._nod_pending
                or self.mode != "static" or self.intensity > 0.02 or bool(self._extra))

    def action_name(self):
        if self.mode == "idle":
            return self._idle.name
        return None

    def tick(self, now, dt):
        """프레임·움직임을 갱신한다. 값이 바뀌면 True."""
        self._t = now
        if self._hop_pending:
            self._hop_pending = False
            self._hop = (now, self._hop_height * self.rng.uniform(0.8, 1.2), self.rng.choice((1, 2)), self.rng.uniform(0.45, 0.6))
        if self._nod_pending:
            self._nod_pending, self._nod_t0 = False, now
        extra = {}
        if self.mode == "idle":
            frame, extra, hop = self._idle.update(now, self.peers())
            self._set_frame(frame)
            if hop:
                self.hop()
        elif self.mode == "type" and self._typer is not None:
            self._set_frame(self._typer.update(now, self.intensity))
        inten = max(0.0, min(1.0, self.intensity))
        self._extra = extra
        typing = self.mode == "type"
        freq = 0.8 + 0.8 * inten                                       # 천천히
        self._phase += dt * freq * 6.2832
        self._phase2 += dt * 0.35 * 6.2832
        H = self.bank.ch * self.scale
        calm = 0.0 if typing else 0.35                                # 키보드를 칠 땐 몸·책상이 전혀 움직이지 않는다
        dy = -(0.003 * H) * math.sin(self._phase2) * (0.0 if typing else 1.0)   # 숨쉬기
        dy += -(0.016 * H * inten * calm) * abs(math.sin(self._phase))
        tilt = 2.6 * inten * calm * math.sin(self._phase * 0.5 + 0.8)
        dx = 0.7 * inten * calm * math.sin(self._phase * 1.5)
        if extra and not typing:                                       # 동작이 요구하는 움직임(느리고 작게)
            hz_t, hz_b = min(0.6, extra.get("tilt_hz", 0.5) * 0.5), min(0.7, extra.get("bob_hz", 0.5) * 0.45)
            tilt += 0.5 * extra.get("tilt", 0.0) * math.sin(2 * math.pi * hz_t * now + self._phase2)
            dy -= 0.5 * extra.get("bob", 0.0) * H * abs(math.sin(2 * math.pi * hz_b * now + self._phase2))
        if self._hop is not None and not typing:                       # 통통 뜀 (캐릭터마다 높이·횟수·속도가 다름)
            t0, h, count, per = self._hop
            t = max(0.0, now - t0)
            if t > per * count:
                self._hop = None
            else:
                dy -= h * H * abs(math.sin(math.pi * t / per))
        if self._nod_t0 is not None:                                   # 끄덕끄덕
            t = max(0.0, now - self._nod_t0)
            if t > 0.9:
                self._nod_t0 = None
            else:
                k = math.exp(-2.0 * t)
                tilt += 0.0
                dy += 0.0
        new = (round(dy, 2), round(tilt, 2), round(dx, 2))
        if new != self._motion:
            self._motion = new
            self.update()
            return True
        return False

    def swing(self):
        return self._motion[1]

    def _transform(self):
        cw, ch, padx, pady = self._geom()
        dy, tilt, dx = self._motion
        pivot = QPointF(padx + cw / 2, pady + ch)                     # 발끝 중앙
        t = QTransform()
        t.translate(dx, dy)
        t.translate(pivot.x(), pivot.y())
        t.rotate(tilt)
        t.translate(-pivot.x(), -pivot.y())
        return t, padx, pady

    def anchor_global(self):
        """머리(귀) 꼭대기 중앙의 전역 좌표(현재 움직임 반영). 쪽지의 아래 중앙이 여기에 온다."""
        cw, ch, padx, pady = self._geom()
        top = self.bank.head_top(self.frame) * self.scale
        t, _, _ = self._transform()
        pt = t.map(QPointF(padx + cw / 2, pady + top))
        return self.mapToGlobal(QPoint(int(round(pt.x())), int(round(pt.y()))))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t, padx, pady = self._transform()
        p.setTransform(t)
        pm = self.bank.pixmap(self.frame, self.scale, self.devicePixelRatioF())
        p.drawPixmap(QPoint(int(round(padx)), int(round(pady))), pm)

    # -- 마우스 -------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press, self._last, self._dragging = e.globalPos(), e.globalPos(), False
        elif e.button() == Qt.RightButton:
            self.context_requested.emit(self)

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        if not self._dragging and (e.globalPos() - self._press).manhattanLength() > 5:
            self._dragging = True
        if self._dragging:
            step = e.globalPos() - self._last
            self._last = e.globalPos()
            if not step.isNull():
                self.move(self.pos() + step)
                if e.modifiers() & Qt.ShiftModifier:               # Shift+끌기: 모두 함께
                    self.group_step.emit(self, step)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        was_drag = self._dragging
        self._press, self._dragging = None, False
        (self.drag_ended if was_drag else self.clicked).emit(self)

    def moveEvent(self, _e):
        self.moved.emit(self)

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.wheel_scaled.emit(self, 1.1 ** steps, bool(e.modifiers() & Qt.ControlModifier))
        e.accept()

    def enterEvent(self, _e):
        self.setWindowOpacity(1.0)

    def leaveEvent(self, _e):
        self.setWindowOpacity(self.opacity)
