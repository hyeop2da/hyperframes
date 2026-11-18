"""캐릭터 한 마리 = 투명 창 하나.

* 포즈는 4가지(기본/집중/휴식/응원)만 쓰고, 작업 중에는 포즈를 바꾸는 대신
  작은 상하 움직임과 기울기(= 노트에 글을 쓰는 듯한 반응)로 표현한다.
* 모든 움직임은 '그리기 변환'으로 처리하므로 창 마스크(클릭 영역)는 포즈가 바뀔 때만 갱신한다.
"""
import json
import math
import random
from pathlib import Path

from PyQt5.QtCore import QPoint, QPointF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QPainter, QPixmap, QRegion, QTransform
from PyQt5.QtWidgets import QApplication, QWidget

POSES = ("base", "focus", "rest", "cheer")
POSE_LABEL = {"base": "기본", "focus": "집중", "rest": "휴식", "cheer": "응원"}
CHAR_LABEL = {"chiikawa": "치이카와", "hachiware": "하치와레", "usagi": "우사기"}
CHARS = ("chiikawa", "hachiware", "usagi")

SCALE_MIN, SCALE_MAX = 0.08, 3.0
SIZE_PRESETS = [("초소형", 0.12), ("아주 작게", 0.2), ("작게", 0.3), ("조금 작게", 0.4),
                ("보통", 0.5), ("크게", 0.8), ("아주 크게", 1.1)]


class PoseBank:
    """frames/poses/*.png 를 읽어 (크기별) 캐시해 두는 저장소."""

    def __init__(self, pose_dir):
        pose_dir = Path(pose_dir)
        meta = json.loads((pose_dir / "manifest.json").read_text(encoding="utf-8"))
        self.cw, self.ch = meta["canvas"]
        self._top = {k: v["bbox"][1] for k, v in meta.get("poses", {}).items()}   # 포즈별 머리(귀) 꼭대기 y
        self._raw = {}
        for ch in CHARS:
            for pose in POSES:
                pm = QPixmap(str(pose_dir / f"{ch}_{pose}.png"))
                if not pm.isNull():
                    self._raw[(ch, pose)] = pm
        self._pix, self._reg = {}, {}

    def has(self, ch):
        return all((ch, p) in self._raw for p in POSES)

    def raw(self, ch, pose):
        return self._raw[(ch, pose)]

    def head_top(self, ch, pose):
        return self._top.get(f"{ch}_{pose}", 0)

    def clear_cache(self):
        self._pix.clear()
        self._reg.clear()

    def pixmap(self, ch, pose, scale, dpr):
        key = (ch, pose, round(scale, 3), dpr)
        pm = self._pix.get(key)
        if pm is None:
            src = self._raw[(ch, pose)]
            size = QSize(max(1, round(src.width() * scale * dpr)), max(1, round(src.height() * scale * dpr)))
            pm = src.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._pix[key] = pm
        return pm

    def region(self, ch, pose, scale):
        key = (ch, pose, round(scale, 3))
        reg = self._reg.get(key)
        if reg is None:
            src = self._raw[(ch, pose)]
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
    wheel_scaled = pyqtSignal(object, float, bool)   # (펫, 배율 변화, 전체 적용 여부)

    def __init__(self, char, bank, scale=0.5, opacity=0.85, on_top=True):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.char, self.bank = char, bank
        self.scale = min(SCALE_MAX, max(SCALE_MIN, scale))
        self.opacity = opacity
        self.pose = "base"
        self.intensity = 0.0
        self._phase = random.uniform(0, 6.28)
        self._phase2 = random.uniform(0, 6.28)
        self._hop_t0 = None
        self._nod_t0 = None
        self._hop_pending = False
        self._nod_pending = False
        self._motion = (0.0, 0.0, 0.0)         # (세로 이동 px, 기울기°, 가로 이동 px)
        self._press = None
        self._dragging = False
        self._origin = QPoint()
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
        reg = self.bank.region(self.char, self.pose, self.scale).translated(int(padx), int(pady))
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

    def set_pose(self, pose):
        if pose != self.pose and (self.char, pose) in self.bank._raw:
            self.pose = pose
            self._refresh_mask()
            self.update()

    def set_opacity(self, v):
        self.opacity = v
        self.setWindowOpacity(1.0 if self.underMouse() else v)

    # -- 움직임 -------------------------------------------------------------
    def hop(self):
        self._hop_pending = True          # 시작 시각은 다음 틱의 시각을 기준으로 잡는다(시계를 하나로 통일)

    def nod(self):
        self._nod_pending = True

    def busy(self):
        return (self._hop_t0 is not None or self._nod_t0 is not None
                or self._hop_pending or self._nod_pending)

    def tick(self, now, dt):
        """강도(0~1)에 따라 상하·기울기를 계산한다. 값이 바뀌면 True."""
        if self._hop_pending:
            self._hop_pending, self._hop_t0 = False, now
        if self._nod_pending:
            self._nod_pending, self._nod_t0 = False, now
        inten = max(0.0, min(1.0, self.intensity))
        freq = 1.3 + 2.3 * inten                                      # 글 쓰는 속도
        self._phase += dt * freq * 6.2832
        self._phase2 += dt * 0.35 * 6.2832                            # 아주 느린 숨쉬기
        H = self.bank.ch * self.scale
        dy = -(0.004 * H) * math.sin(self._phase2)                    # 숨쉬기(항상)
        dy += -(0.016 * H * inten) * abs(math.sin(self._phase))        # 작업 중 상하
        tilt = 2.6 * inten * math.sin(self._phase * 0.5 + 0.8)
        dx = 0.7 * inten * math.sin(self._phase * 1.5)
        if self._hop_t0 is not None:                                   # 응원: 통통 3번
            t = max(0.0, now - self._hop_t0)
            if t > 0.75:
                self._hop_t0 = None
            else:
                dy -= 0.075 * H * abs(math.sin(math.pi * t / 0.25))
        if self._nod_t0 is not None:                                   # 끄덕끄덕
            t = max(0.0, now - self._nod_t0)
            if t > 0.9:
                self._nod_t0 = None
            else:
                k = math.exp(-2.0 * t)
                tilt += 7.0 * k * math.sin(2 * math.pi * 2.4 * t)
                dy += 0.012 * H * k * abs(math.sin(2 * math.pi * 2.4 * t))
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
        top = self.bank.head_top(self.char, self.pose) * self.scale
        t, _, _ = self._transform()
        pt = t.map(QPointF(padx + cw / 2, pady + top))
        return self.mapToGlobal(QPoint(int(round(pt.x())), int(round(pt.y()))))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t, padx, pady = self._transform()
        p.setTransform(t)
        pm = self.bank.pixmap(self.char, self.pose, self.scale, self.devicePixelRatioF())
        p.drawPixmap(QPoint(int(round(padx)), int(round(pady))), pm)

    # -- 마우스 -------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press, self._origin, self._dragging = e.globalPos(), self.pos(), False
        elif e.button() == Qt.RightButton:
            self.context_requested.emit(self)

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        delta = e.globalPos() - self._press
        if not self._dragging and delta.manhattanLength() > 5:
            self._dragging = True
        if self._dragging:
            self.move(self._origin + delta)

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
