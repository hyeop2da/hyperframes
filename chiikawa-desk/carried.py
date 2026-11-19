"""머리 위에 올리는 물건의 공통 기반 (포스트잇 · 타이머 · 퇴근 시계).

폴드 메모의 포스트잇 모양을 따른다: 종이 색 그라데이션, 모서리 반경 16, 위쪽의 접힌 자국, 접고 펼 때 280ms 의
부드러운 크기 변화와 빛이 훑고 지나가는 효과.

  * 접힌 모습(mini): 머리 위의 작은 쪽지. 누르면 펼쳐진다.
  * 펼친 모습(open): 내용이 보이는 카드. 머리줄의 접기 버튼이나 Esc 로 다시 접는다.
  * 두 손으로 아래 모서리를 잡고 있고, 캐릭터의 움직임(기울기)에 맞춰 흔들린다.
  * 쪽지/카드를 끌면 캐릭터가 같이 옮겨진다(Shift 를 누르고 끌면 모두).
"""
import math
import time

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

MARGIN = 14                    # 그림자·흔들림 여백
MINI_W, MINI_H = 56, 50        # 접힌 쪽지(기준 크기, 타이머·퇴근 시계)
HEADER_H = 36                  # 펼친 카드의 머리줄
BTN = 26                       # 머리줄 버튼 크기
GAP = 3                        # 머리와 쪽지 사이 간격
OPEN_RADIUS = 16
ANIM_SECONDS = 0.28
SHOW_AT = 0.82                 # 이만큼 펼쳐진 뒤에 내용(글·버튼)을 보인다
SETTINGS = {"animate": True}   # 시험에서는 끌 수 있다
FONT_FAMILIES = ["Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "Segoe UI", "Sans Serif"]


def make_font(pt, bold=False, italic=False):
    f = QFont()
    if hasattr(f, "setFamilies"):
        f.setFamilies(FONT_FAMILIES)
    else:
        f.setFamily(FONT_FAMILIES[0])
    f.setPointSizeF(pt)
    f.setBold(bold)
    f.setItalic(italic)
    return f


def mix(c, r, g, b, amt):
    return QColor(int(c.red() * (1 - amt) + r * amt), int(c.green() * (1 - amt) + g * amt),
                  int(c.blue() * (1 - amt) + b * amt), c.alpha())


def paper_from(base, dark=False):
    """종이 색 하나로 그라데이션·카드·글자색 등을 만든다(폴드 메모의 Apply-StickyTheme 와 같은 계산)."""
    if dark:
        return dict(base=base, tint_a=QColor(58, 60, 66), tint_b=QColor(36, 38, 42), card=QColor(48, 50, 56),
                    text=QColor(242, 242, 247), muted=QColor(160, 160, 168), line=QColor(255, 255, 255, 40),
                    crease=QColor(255, 255, 255, 50), hover=QColor(255, 255, 255, 36), dark=True)
    return dict(base=base, tint_a=mix(base, 255, 255, 255, 0.06), tint_b=mix(base, 0, 0, 0, 0.04),
                card=mix(base, 255, 255, 255, 0.22), text=QColor(40, 40, 36), muted=QColor(96, 96, 88),
                line=QColor(0, 0, 0, 24), crease=QColor(255, 255, 255, 70), hover=QColor(0, 0, 0, 28), dark=False)


def ease_out_cubic(u):
    return 1.0 - (1.0 - max(0.0, min(1.0, u))) ** 3


class CarriedItem(QWidget):
    layout_changed = pyqtSignal(object)        # 펼침/접힘/색 변경 → 위치 다시 맞추기
    drag_step = pyqtSignal(object, bool)       # (끈 만큼의 QPoint, Shift 여부) → 캐릭터를 옮김
    rename_requested = pyqtSignal()            # 제목을 더블클릭

    OPEN_W, OPEN_H = 156, 148
    MINI_RADIUS = 9
    DOUBLE_CLICK_RENAME = False                # 접힌 쪽지를 한 번 누르면 280ms 뒤 펼치고, 더블클릭이면 이름 바꾸기
    CLICK_DELAY_MS = 280

    def __init__(self, on_top=True):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.setMouseTracking(True)
        self.setWindowOpacity(0.98)
        self.clock = time.monotonic            # 관리자가 자기 시계로 바꿔 준다(시험·영상 재현용)
        self.mscale = 1.0
        self._open = False
        self._prog = 0.0                       # 0 = 접힘, 1 = 펼침 (애니메이션 진행도)
        self._anim = None
        self._anchor = None
        self._swing = 0.0
        self._rs = None
        self._badge = ""
        self._alert_until = 0.0
        self._press = None
        self._last = None
        self._press_btn = None
        self._drag_ok = False
        self._dragging = False
        self._hover = None
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.open_full)

    # -- 하위 클래스가 채우는 부분 -------------------------------------------
    def accent(self):
        return QColor("#FCEB9C")

    def paper(self):
        return paper_from(self.accent())

    def open_size(self):
        return float(self.OPEN_W), float(self.OPEN_H)

    def mini_size(self):
        return MINI_W * self.mscale, MINI_H * self.mscale

    def mini_radius(self):
        return self.MINI_RADIUS

    def paint_mini(self, p, r, paper):
        pass

    def paint_open(self, p, r, paper):
        pass

    def on_layout(self, r, show):
        """펼쳤을 때 자식 위젯 배치(r = 현재 카드 영역, show = 내용을 보여야 하는가)."""

    def extra_buttons(self):
        return {}

    def draw_extra_icon(self, p, name, rect, color):
        pass

    def button_clicked(self, name):
        pass

    def build_menu(self, m):
        m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)

    def opened_changed(self, is_open):
        pass

    # -- 상태·애니메이션 -----------------------------------------------------
    def is_open(self):
        return self._open

    def _store_open(self, value):
        self._open = bool(value)

    def init_progress(self):
        self._prog = 1.0 if self._open else 0.0

    def animating(self):
        return self._anim is not None

    def cur_size(self):
        mw, mh = self.mini_size()
        ow, oh = self.open_size()
        return mw + (ow - mw) * self._prog, mh + (oh - mh) * self._prog

    def note_rect(self):
        cw, ch = self.cur_size()
        return QRectF(MARGIN, MARGIN, cw, ch)

    def apply_layout(self):
        r = self.note_rect()
        self.setFixedSize(int(round(r.width() + 2 * MARGIN)), int(round(r.height() + 2 * MARGIN)))
        self.on_layout(r, self._open and self._prog >= SHOW_AT)
        if self._anchor is not None:
            self._reposition()
        self.update()

    def set_mini_scale(self, s):
        if abs(s - self.mscale) > 0.01:
            self.mscale = s
            if not self._open and not self.animating():
                self.apply_layout()

    def start_anim(self, target):
        if not SETTINGS["animate"]:
            self._prog, self._anim = float(target), None
            self.apply_layout()
            return
        self._anim = {"t0": self.clock(), "a": self._prog, "b": float(target)}
        self.apply_layout()

    def step_anim(self, now):
        """관리자가 틱마다 부른다. 진행 중이면 True."""
        a = self._anim
        if a is None:
            return False
        u = (now - a["t0"]) / ANIM_SECONDS
        if u >= 1.0:
            self._prog, self._anim = a["b"], None
        else:
            self._prog = a["a"] + (a["b"] - a["a"]) * ease_out_cubic(u)
        self.apply_layout()
        return self._anim is not None

    def finish_animation(self):
        if self._anim is not None:
            self._prog, self._anim = self._anim["b"], None
            self.apply_layout()

    def set_open(self, value):
        value = bool(value)
        if value == self._open:
            return
        self._store_open(value)
        self.start_anim(1.0 if value else 0.0)
        self.layout_changed.emit(self)
        self.opened_changed(value)

    def open_full(self):
        self.set_open(True)

    def collapse(self):
        self.set_open(False)

    def toggle(self):
        self.set_open(not self._open)

    # -- 위치·흔들림·알림 ----------------------------------------------------
    def place_above(self, anchor):
        """카드의 아래 중앙이 머리 위 기준점(anchor, 전역 좌표)에 오도록 옮긴다."""
        self._anchor = anchor
        self._reposition()

    def _reposition(self):
        anchor = self._anchor
        r = self.note_rect()
        x = anchor.x() - (r.x() + r.width() / 2)
        y = anchor.y() - GAP - (r.y() + r.height())
        scr = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        a = scr.availableGeometry()
        x = max(a.left() - int(r.x()) + 2, min(x, a.right() - int(r.x() + r.width()) - 2))
        y = max(a.top() - int(r.y()) + 2, y)
        self.move(int(round(x)), int(round(y)))

    def set_swing(self, deg):
        if abs(deg - self._swing) > 0.05:
            self._swing = deg
            if self._prog < 0.5:
                self.update()

    def set_badge(self, text):
        if text != self._badge:
            self._badge = text
            self.update()

    def alert(self, seconds=6.0):
        self._alert_until = time.monotonic() + seconds
        self.update()

    def alerting(self):
        return time.monotonic() < self._alert_until

    # -- 머리줄 버튼 ---------------------------------------------------------
    def header_button(self, index):
        """오른쪽부터 index 번째 머리줄 버튼 영역(0 = 가장 오른쪽)."""
        r = self.note_rect()
        return QRectF(r.right() - 10 - BTN - index * (BTN + 3), r.y() + (HEADER_H - BTN) / 2, BTN, BTN)

    def buttons(self):
        out = {"collapse": self.header_button(0)}
        out.update(self.extra_buttons())
        return out

    def _button_at(self, pos):
        if not (self._open and self._prog >= SHOW_AT):
            return None
        for name, rect in self.buttons().items():
            if rect.contains(QPointF(pos)):
                return name
        return None

    @staticmethod
    def draw_icon(p, kind, rect, color):
        c = rect.center()
        pen = QPen(color, 1.7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if kind == "collapse":                                    # 접기: 아래로 향한 꺾쇠
            p.drawLine(QPointF(c.x() - 5, c.y() - 2.5), QPointF(c.x(), c.y() + 2.5))
            p.drawLine(QPointF(c.x(), c.y() + 2.5), QPointF(c.x() + 5, c.y() - 2.5))
        elif kind == "close":                                     # 삭제: ×
            p.drawLine(QPointF(c.x() - 4.5, c.y() - 4.5), QPointF(c.x() + 4.5, c.y() + 4.5))
            p.drawLine(QPointF(c.x() - 4.5, c.y() + 4.5), QPointF(c.x() + 4.5, c.y() - 4.5))
        elif kind == "note":                                      # 색 바꾸기: 모서리가 접힌 포스트잇
            path = QPainterPath()
            path.moveTo(c.x() - 6, c.y() - 6)
            path.lineTo(c.x() + 6, c.y() - 6)
            path.lineTo(c.x() + 6, c.y() + 2)
            path.lineTo(c.x() + 2, c.y() + 6)
            path.lineTo(c.x() - 6, c.y() + 6)
            path.closeSubpath()
            p.drawPath(path)
            p.drawLine(QPointF(c.x() + 2, c.y() + 6), QPointF(c.x() + 2, c.y() + 2))
            p.drawLine(QPointF(c.x() + 2, c.y() + 2), QPointF(c.x() + 6, c.y() + 2))

    # -- 그리기 -------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.note_rect()
        paper = self.paper()
        prog = self._prog
        radius = self.mini_radius() + (OPEN_RADIUS - self.mini_radius()) * prog
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        for i in range(1, 7):                             # 부드러운 그림자
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, max(2, 26 - i * 4)))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), radius + i, radius + i)
        # 종이: 위(+6% 밝게) → 아래(-4% 어둡게) 그라데이션
        p.save()
        p.setClipPath(path)
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        grad.setColorAt(0.0, paper["tint_a"])
        grad.setColorAt(1.0, paper["tint_b"])
        p.fillRect(r, grad)
        p.restore()
        p.setPen(QPen(paper["line"], 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if prog > 0.25:                                   # 위쪽의 접힌 자국
            cy = r.y() + max(10.0, radius / 2.0)
            col = QColor(paper["crease"])
            col.setAlpha(int(col.alpha() * min(1.0, (prog - 0.25) / 0.5)))
            p.setPen(QPen(col, 1))
            p.drawLine(QPointF(r.x() + radius, cy), QPointF(r.right() - radius, cy))
        if prog <= 0.04:
            self.paint_mini(p, r, paper)
        elif self._open and prog >= SHOW_AT:
            self._paint_header_buttons(p, paper)
            self.paint_open(p, r, paper)
            if self.RESIZABLE:
                self._paint_grip(p, paper)
        if self._anim is not None:                        # 빛이 훑고 지나가는 효과
            h = max(28.0, r.height() / 8.0)
            y = r.y() + prog * r.height()
            band = QRectF(r.x(), y - h / 2, r.width(), h)
            g = QLinearGradient(band.topLeft(), band.bottomLeft())
            g.setColorAt(0.0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 255, 80))
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.save()
            p.setClipPath(path)
            p.fillRect(band, g)
            p.restore()
        self._paint_hands(p, r)
        if self.alerting() and int(time.monotonic() * 1.0) % 2 == 0:      # 마감·알림: 테두리가 천천히 켜졌다 꺼짐(흔들리지 않음)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#E5484D"), 2.5))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius, radius)
        if self._badge:
            self._paint_badge(p, r)

    def _paint_header_buttons(self, p, paper):
        for name, rect in self.buttons().items():
            if name == self._hover:                       # 마우스를 올리면 살짝 어두워짐(폴드 메모의 Hover)
                p.setPen(Qt.NoPen)
                p.setBrush(paper["hover"])
                p.drawRoundedRect(rect, 8, 8)
            if name == "collapse":
                self.draw_icon(p, "collapse", rect, paper["text"])
            else:
                self.draw_extra_icon(p, name, rect, paper["text"])

    def _paint_hands(self, p, r):
        """아래 모서리를 잡은 작은 두 손."""
        rad = max(3.5, min(5.5, 5.0 * max(self.mscale, self._prog)))
        p.setPen(QPen(QColor("#3b2f2f"), 1.5))
        p.setBrush(QColor("#FFFFFF"))
        inset = rad + 6
        for cx in (r.left() + inset, r.right() - inset):
            p.drawEllipse(QPointF(cx, r.bottom() + 1.0), rad, rad)

    def _paint_badge(self, p, r):
        p.save()
        p.translate(r.right() - 18, r.y() + 14)
        p.rotate(-14)
        f = make_font(8, True)
        p.setFont(f)
        w = QFontMetrics(f).horizontalAdvance(self._badge) + 12
        box = QRectF(-w / 2, -9, w, 18)
        p.setPen(QPen(QColor("#E5484D"), 2))
        p.setBrush(QColor(255, 255, 255, 220))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor("#E5484D"))
        p.drawText(box, Qt.AlignCenter, self._badge)
        p.restore()

    # -- 마우스 -------------------------------------------------------------
    # -- 크기 조절(왼쪽 위 모서리를 끈다: 아래 중앙이 머리에 붙어 있으므로 위·양옆으로 늘어난다) --
    RESIZABLE = False
    GRIP = 16

    def grip_rect(self):
        r = self.note_rect()
        return QRectF(r.x(), r.y(), self.GRIP, self.GRIP)

    def in_grip(self, pos):
        return self.RESIZABLE and self._open and self._prog >= SHOW_AT and self.grip_rect().contains(QPointF(pos))

    def resize_to(self, w, h):
        pass

    def resize_done(self):
        pass

    def _paint_grip(self, p, paper):
        g = self.grip_rect()
        p.setPen(QPen(paper["muted"], 1.4, Qt.SolidLine, Qt.RoundCap))
        for k in (4.0, 8.0, 12.0):
            p.drawLine(QPointF(g.x() + k, g.y() + 3.0), QPointF(g.x() + 3.0, g.y() + k))

    def in_header(self, pos):
        r = self.note_rect()
        return self._open and self._prog >= SHOW_AT and r.x() <= pos.x() <= r.right() and r.y() <= pos.y() < r.y() + HEADER_H

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            m = QMenu(self)
            self.build_menu(m)
            from PyQt5.QtGui import QCursor
            m.exec_(QCursor.pos())
            return
        if e.button() != Qt.LeftButton:
            return
        self._press, self._last, self._dragging = e.globalPos(), e.globalPos(), False
        self._rs = (e.globalPos(), self.open_size()) if self.in_grip(e.pos()) else None
        self._press_btn = self._button_at(e.pos())
        self._drag_ok = (not self._open) or (self._press_btn is None and self.in_header(e.pos()))

    def mouseMoveEvent(self, e):
        if self._press is not None and self._rs is not None:
            if e.buttons() & Qt.LeftButton:
                g0, (w0, h0) = self._rs
                d = e.globalPos() - g0
                self._dragging = True
                self.resize_to(w0 - 2 * d.x(), h0 - d.y())      # 모서리가 포인터를 따라온다
            return
        if self._press is None:
            self.setCursor(Qt.SizeFDiagCursor if self.in_grip(e.pos()) else Qt.ArrowCursor)
            hov = self._button_at(e.pos())
            if hov != self._hover:
                self._hover = hov
                self.update()
            return
        if not (e.buttons() & Qt.LeftButton) or not self._drag_ok:
            return
        if not self._dragging and (e.globalPos() - self._press).manhattanLength() > 5:
            self._dragging = True
        if self._dragging:
            delta = e.globalPos() - self._last
            self._last = e.globalPos()
            if not delta.isNull():
                self.drag_step.emit(delta, bool(e.modifiers() & Qt.ShiftModifier))

    def leaveEvent(self, _e):
        if self._hover is not None:
            self._hover = None
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        btn, was_drag = self._press_btn, self._dragging
        resized, self._rs = self._rs is not None, None
        self._press, self._press_btn, self._dragging = None, None, False
        if resized:
            self.resize_done()
            return
        if was_drag:
            return
        if not self._open:
            if self.note_rect().adjusted(-6, -6, 6, 6).contains(QPointF(e.pos())):
                if self.DOUBLE_CLICK_RENAME and self.CLICK_DELAY_MS > 0:
                    self._click_timer.start(self.CLICK_DELAY_MS)       # 더블클릭이면 펼치지 않고 이름 바꾸기
                else:
                    self.open_full()
        elif btn == "collapse":
            self.collapse()
        elif btn:
            self.button_clicked(btn)

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton or not self.DOUBLE_CLICK_RENAME:
            return
        if not self._open or (self.in_header(e.pos()) and self._button_at(e.pos()) is None):
            self._click_timer.stop()
            self.rename_requested.emit()
