"""머리 위에 올리는 물건의 공통 기반 (포스트잇 · 타이머 · 퇴근 시계).

* 접힌 모습(mini): 머리 위의 작은 쪽지. 누르면 펼쳐진다.
* 펼친 모습(open): 내용이 보이는 정사각형 카드. 머리줄의 '–' 로 다시 접는다.
* 두 손으로 아래 모서리를 잡고 있고, 캐릭터의 움직임(기울기)에 맞춰 흔들린다.
* 쪽지/카드를 끌면 캐릭터가 같이 옮겨진다(Shift 를 누르고 끌면 모두).
"""
import math
import time

from PyQt5.QtCore import QPoint, QPointF, QPropertyAnimation, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

SH = 10                        # 펼친 카드의 그림자 여백
MINI_W, MINI_H = 56, 50        # 접힌 쪽지(기준 크기)
MINI_M = 14                    # 쪽지가 흔들려도 잘리지 않게 두는 여백
HEADER_H = 28
GAP = 3                        # 머리와 쪽지 사이 간격
FONT_FAMILIES = ["Malgun Gothic", "Apple SD Gothic Neo", "Noto Sans CJK KR", "NanumGothic", "Segoe UI", "Sans Serif"]


def make_font(pt, bold=False):
    f = QFont()
    if hasattr(f, "setFamilies"):
        f.setFamilies(FONT_FAMILIES)
    else:
        f.setFamily(FONT_FAMILIES[0])
    f.setPointSizeF(pt)
    f.setBold(bold)
    return f


class CarriedItem(QWidget):
    layout_changed = pyqtSignal(object)        # 펼침/접힘/색 변경 → 위치 다시 맞추기
    drag_step = pyqtSignal(object, bool)       # (끈 만큼의 QPoint, Shift 여부) → 캐릭터를 옮김

    OPEN_W, OPEN_H = 156, 148

    def __init__(self, on_top=True):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.mscale = 1.0
        self._open = False
        self._swing = 0.0
        self._badge = ""
        self._alert_until = 0.0
        self._press = None
        self._last = QPoint()
        self._press_btn = None
        self._drag_ok = False
        self._dragging = False

    # -- 하위 클래스가 채우는 부분 -------------------------------------------
    def accent(self):
        return QColor("#FCEB9C")

    def paint_mini(self, p, r, base):
        pass

    def paint_open(self, p, r, base):
        pass

    def on_layout(self, r):
        """펼쳤을 때 자식 위젯 배치(r = 카드 영역)."""

    def extra_buttons(self):
        return {}

    def button_clicked(self, name):
        pass

    def build_menu(self, m):
        m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)

    # -- 상태 ---------------------------------------------------------------
    def is_open(self):
        return self._open

    def _store_open(self, value):
        self._open = bool(value)

    def mini_size(self):
        return MINI_W * self.mscale, MINI_H * self.mscale

    def note_rect(self):
        if self.is_open():
            return QRectF(SH, SH, self.OPEN_W, self.OPEN_H)
        w, h = self.mini_size()
        return QRectF(MINI_M, MINI_M, w, h)

    def apply_layout(self):
        r = self.note_rect()
        if self.is_open():
            self.setFixedSize(self.OPEN_W + 2 * SH, self.OPEN_H + 2 * SH)
        else:
            w, h = self.mini_size()
            self.setFixedSize(int(w + 2 * MINI_M), int(h + 2 * MINI_M))
        self.on_layout(r)
        self.update()

    def set_mini_scale(self, s):
        if abs(s - self.mscale) > 0.01:
            self.mscale = s
            if not self.is_open():
                self.apply_layout()

    def set_open(self, value):
        if bool(value) == self.is_open():
            return
        self._store_open(value)
        self.apply_layout()
        self._fade()
        self.layout_changed.emit(self)
        self.opened_changed(bool(value))

    def opened_changed(self, is_open):
        pass

    def open_full(self):
        self.set_open(True)

    def collapse(self):
        self.set_open(False)

    def toggle(self):
        self.set_open(not self.is_open())

    def _fade(self):
        self.setWindowOpacity(0.35)
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(150)
        self._anim.setStartValue(0.35)
        self._anim.setEndValue(1.0)
        self._anim.start()

    # -- 위치·흔들림·알림 ----------------------------------------------------
    def place_above(self, anchor):
        """카드의 아래 중앙이 머리 위 기준점(anchor, 전역 좌표)에 오도록 옮긴다."""
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
            if not self.is_open():
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

    # -- 그리기 -------------------------------------------------------------
    def buttons(self):
        r = self.note_rect()
        out = {"collapse": QRectF(r.right() - 26, r.y() + 5, 20, 20)}
        out.update(self.extra_buttons())
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.note_rect()
        base = self.accent()
        open_ = self.is_open()
        swing = self._swing
        if not open_ and self.alerting():
            swing += 9.0 * math.sin(time.monotonic() * 22.0)
        if not open_:                                      # 머리(아래 중앙)를 축으로 흔들림
            p.translate(r.center().x(), r.bottom())
            p.rotate(swing)
            p.translate(-r.center().x(), -r.bottom())
        radius = 9
        for i in range(1, 7):                              # 부드러운 그림자
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, max(2, 26 - i * 4)))
            p.drawRoundedRect(r.adjusted(-i, -i + 3, i, i + 3), radius + i, radius + i)
        p.setPen(Qt.NoPen)
        p.setBrush(base)
        p.drawRoundedRect(r, radius, radius)
        if open_:
            band = QPainterPath()
            band.addRoundedRect(QRectF(r.x(), r.y(), r.width(), HEADER_H), 9, 9)
            band.addRect(QRectF(r.x(), r.y() + 14, r.width(), HEADER_H - 14))
            p.setBrush(base.darker(105))
            p.drawPath(band.simplified())
            p.setPen(QPen(QColor("#6b6657"), 1.7, Qt.SolidLine, Qt.RoundCap))
            c = self.buttons()["collapse"].center()        # '–' 접기
            p.drawLine(QPointF(c.x() - 5, c.y() + 2), QPointF(c.x() + 5, c.y() + 2))
            self.paint_open(p, r, base)
        else:
            self.paint_mini(p, r, base)
        self._paint_hands(p, r)
        if self.alerting() and int(time.monotonic() * 4) % 2 == 0:      # 마감·알림: 테두리 깜빡
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#E5484D"), 2.5))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius, radius)
        if self._badge:
            self._paint_badge(p, r)

    def _paint_hands(self, p, r):
        """아래 모서리를 잡은 작은 두 손."""
        rad = 5.0 if self.is_open() else max(3.5, 5.0 * self.mscale)
        p.setPen(QPen(QColor("#3b2f2f"), 1.5))
        p.setBrush(QColor("#FFFFFF"))
        inset = rad + 3
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
        self._press_btn = None
        self._drag_ok = not self.is_open()                      # 접힌 쪽지는 어디를 끌어도 됨
        if self.is_open():
            for name, rect in self.buttons().items():
                if rect.contains(QPointF(e.pos())):
                    self._press_btn = name
            r = self.note_rect()
            self._drag_ok = (self._press_btn is None) and e.pos().y() < r.y() + HEADER_H

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton) or not self._drag_ok:
            return
        if not self._dragging and (e.globalPos() - self._press).manhattanLength() > 5:
            self._dragging = True
        if self._dragging:
            delta = e.globalPos() - self._last
            self._last = e.globalPos()
            if not delta.isNull():
                self.drag_step.emit(delta, bool(e.modifiers() & Qt.ShiftModifier))

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        btn, was_drag = self._press_btn, self._dragging
        self._press, self._press_btn, self._dragging = None, None, False
        if was_drag:
            return
        if not self.is_open():
            if self.note_rect().adjusted(-6, -6, 6, 6).contains(QPointF(e.pos())):
                self.open_full()                                 # 쪽지를 누르면 펼침
        elif btn == "collapse":
            self.collapse()
        elif btn:
            self.button_clicked(btn)
