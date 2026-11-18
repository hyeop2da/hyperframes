"""포스트잇 — 폴드 메모 영상의 노트를 캐릭터가 머리 위로 들고 다닌다.

  * 접힌 모습(mini): 머리 위의 작은 쪽지(제목 + 진행률). 누르면 펼쳐진다.
  * 펼친 모습(full): 제목·본문을 쓰는 정사각형 노트. '–' 버튼이나 Esc 로 다시 접는다.
  * Ctrl+Enter 로 체크리스트, 항목 앞의 ☐ 를 누르면 완료(취소선).  내용은 자동 저장.
"""
import math
import time

from PyQt5.QtCore import QPoint, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor,
)
from PyQt5.QtWidgets import QApplication, QMenu, QTextEdit, QWidget

import notes_store as ns

SH = 10                        # 펼친 노트의 그림자 여백
NOTE_W, NOTE_H = 156, 148      # 펼친 노트
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


class MemoHighlighter(QSyntaxHighlighter):
    """첫 줄은 굵게(제목), 완료(☑) 줄은 취소선 + 회색."""

    def highlightBlock(self, text):
        if self.currentBlock().blockNumber() == 0 and text:
            f = QTextCharFormat()
            f.setFontWeight(QFont.Bold)
            self.setFormat(0, len(text), f)
        if text.startswith(ns.CHECKED):
            f = QTextCharFormat()
            f.setFontStrikeOut(True)
            f.setForeground(QColor("#8a8578"))
            self.setFormat(1, max(0, len(text) - 1), f)


class MemoEdit(QTextEdit):
    escape_pressed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setFont(make_font(9.5))
        self.setStyleSheet("QTextEdit{background:transparent;color:#3a3a3a;selection-background-color:rgba(0,0,0,45);}"
                           "QScrollBar:vertical{width:6px;background:transparent;}"
                           "QScrollBar::handle:vertical{background:rgba(0,0,0,50);border-radius:3px;}"
                           "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.highlighter = MemoHighlighter(self.document())

    @staticmethod
    def _has_box(text):
        return text[:1] in (ns.UNCHECKED, ns.CHECKED)

    def toggle_box_at(self, cur):
        text = cur.block().text()
        if not self._has_box(text):
            return
        mark = ns.UNCHECKED if text[0] == ns.CHECKED else ns.CHECKED
        cur.beginEditBlock()
        cur.setPosition(cur.block().position())
        cur.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
        cur.insertText(mark)
        cur.endEditBlock()

    def ctrl_enter(self):
        """Ctrl+Enter: 줄을 체크리스트로 바꾸고, 이미 체크리스트면 아래에 새 항목을 만든다."""
        cur = self.textCursor()
        if self._has_box(cur.block().text()):
            cur.movePosition(QTextCursor.EndOfBlock)
            cur.insertText("\n" + ns.UNCHECKED + " ")
        else:
            cur.beginEditBlock()
            cur.movePosition(QTextCursor.StartOfBlock)
            cur.insertText(ns.UNCHECKED + " ")
            cur.endEditBlock()
        self.setTextCursor(cur)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            if e.modifiers() & Qt.ControlModifier:
                self.ctrl_enter()
                return
            cur = self.textCursor()
            text = cur.block().text()
            if self._has_box(text) and not cur.hasSelection():
                if text[1:].strip() == "":                       # 빈 항목에서 Enter → 목록 끝내기
                    cur.movePosition(QTextCursor.StartOfBlock)
                    cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
                    cur.removeSelectedText()
                    self.setTextCursor(cur)
                    return
                cur.insertText("\n" + ns.UNCHECKED + " ")
                self.setTextCursor(cur)
                return
        super().keyPressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton and not self.textCursor().hasSelection():
            cur = self.cursorForPosition(e.pos())
            if self._has_box(cur.block().text()) and cur.positionInBlock() <= 1 and e.pos().x() < 28:
                self.toggle_box_at(cur)                           # 누르면 완료 표시


class PostIt(QWidget):
    layout_changed = pyqtSignal(str)          # 펼침/접힘/색 변경 → 위치 다시 맞추기
    task_completed = pyqtSignal(str)          # 체크 항목을 완료함 → 캐릭터가 기뻐함

    def __init__(self, note, store, on_top=True):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.note, self.store = note, store
        self.mscale = 1.0              # 접힌 쪽지 크기(캐릭터 크기에 맞춰 조절)
        self._swing = 0.0
        self._badge = ""
        self._alert_until = 0.0
        self._saved = True
        self._press_btn = None
        self._confirm_until = 0.0
        self._last_done = ns.progress(note.get("text", ""))[0]

        self.edit = MemoEdit(self)
        self.edit.setPlainText(note.get("text", ""))
        self.edit.textChanged.connect(self._on_text)
        self.edit.escape_pressed.connect(self.collapse)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._flush)
        self.apply_layout()

    # -- 모양 ---------------------------------------------------------------
    def is_open(self):
        return bool(self.note.get("open"))

    def _mini_size(self):
        return MINI_W * self.mscale, MINI_H * self.mscale

    def note_rect(self):
        if self.is_open():
            return QRectF(SH, SH, NOTE_W, NOTE_H)
        w, h = self._mini_size()
        return QRectF(MINI_M, MINI_M, w, h)

    def apply_layout(self):
        r = self.note_rect()
        if self.is_open():
            self.setFixedSize(NOTE_W + 2 * SH, NOTE_H + 2 * SH)
            self.edit.setGeometry(int(r.x() + 8), int(r.y() + HEADER_H), int(r.width() - 16), int(r.height() - HEADER_H - 22))
            self.edit.show()
        else:
            w, h = self._mini_size()
            self.setFixedSize(int(w + 2 * MINI_M), int(h + 2 * MINI_M))
            self.edit.hide()
        self.update()

    def set_mini_scale(self, s):
        if abs(s - self.mscale) > 0.01:
            self.mscale = s
            if not self.is_open():
                self.apply_layout()

    def buttons(self):
        r = self.note_rect()
        return {"color": QRectF(r.x() + 6, r.y() + 5, 20, 20),
                "collapse": QRectF(r.right() - 48, r.y() + 5, 20, 20),
                "clear": QRectF(r.right() - 26, r.y() + 5, 20, 20)}

    def place_above(self, anchor):
        """쪽지(노트)의 아래 중앙이 머리 위 기준점(anchor, 전역 좌표)에 오도록 옮긴다."""
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

    def progress(self):
        return ns.progress(self.note.get("text", ""))

    # -- 그리기 -------------------------------------------------------------
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.note_rect()
        base = QColor(ns.COLORS[self.note["color"]])
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
            self._paint_full(p, r, base)
        else:
            self._paint_mini(p, r, base)
        self._paint_hands(p, r)
        if self.alerting() and int(time.monotonic() * 4) % 2 == 0:      # 마감·알림: 테두리 깜빡
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#E5484D"), 2.5))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), radius, radius)
        if self._badge:
            self._paint_badge(p, r)

    def _paint_hands(self, p, r):
        """쪽지 아래 모서리를 잡은 작은 두 손."""
        rad = 5.0 if self.is_open() else max(3.5, 5.0 * self.mscale)
        p.setPen(QPen(QColor("#3b2f2f"), 1.5))
        p.setBrush(QColor("#FFFFFF"))
        inset = rad + 3
        for cx in (r.left() + inset, r.right() - inset):
            p.drawEllipse(QPointF(cx, r.bottom() + 1.0), rad, rad)

    def _paint_full(self, p, r, base):
        band = QPainterPath()
        band.addRoundedRect(QRectF(r.x(), r.y(), r.width(), HEADER_H), 9, 9)
        band.addRect(QRectF(r.x(), r.y() + 14, r.width(), HEADER_H - 14))
        p.setPen(Qt.NoPen)
        p.setBrush(base.darker(105))
        p.drawPath(band.simplified())
        b = self.buttons()
        p.setBrush(base.darker(125))
        p.drawEllipse(b["color"].center(), 6, 6)                  # 색 바꾸기
        p.setPen(QPen(QColor("#6b6657"), 1.7, Qt.SolidLine, Qt.RoundCap))
        c = b["collapse"].center()                                # '–' 접기
        p.drawLine(QPointF(c.x() - 5, c.y() + 2), QPointF(c.x() + 5, c.y() + 2))
        c = b["clear"].center()                                   # '×' 내용 지우기
        confirm = time.monotonic() < self._confirm_until
        p.setPen(QPen(QColor("#D64545") if confirm else QColor("#6b6657"), 1.7, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(c.x() - 4, c.y() - 4), QPointF(c.x() + 4, c.y() + 4))
        p.drawLine(QPointF(c.x() - 4, c.y() + 4), QPointF(c.x() + 4, c.y() - 4))
        p.setPen(QColor("#8d8776"))
        p.setFont(make_font(7.5))
        p.drawText(QRectF(r.x() + 12, r.bottom() - 20, 70, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "저장됨" if self._saved else "저장 중…")
        done, total = self.progress()
        if total:
            p.drawText(QRectF(r.right() - 62, r.bottom() - 20, 50, 16), Qt.AlignRight | Qt.AlignVCenter, f"{done}/{total}")

    def _paint_mini(self, p, r, base):
        s = self.mscale
        p.setPen(Qt.NoPen)
        c = 14 * s
        curl = QPainterPath()                                     # 포스트잇 모서리 접힘
        curl.moveTo(r.right(), r.bottom() - c)
        curl.lineTo(r.right() - c, r.bottom())
        curl.lineTo(r.right(), r.bottom())
        curl.closeSubpath()
        p.setBrush(base.darker(112))
        p.drawPath(curl)
        p.setPen(QColor("#3a3a3a"))
        p.setFont(make_font(max(5.5, 7.5 * s), True))
        inner = r.adjusted(6 * s, 5 * s, -6 * s, -15 * s)
        p.save()
        p.setClipRect(inner)
        p.drawText(inner, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, ns.title_of(self.note.get("text", "")))
        p.restore()
        done, total = self.progress()
        if total and s >= 0.7:
            p.setPen(QColor("#7b7562"))
            p.setFont(make_font(max(5.5, 7 * s)))
            p.drawText(QRectF(r.x() + 6 * s, r.bottom() - 15 * s, 30 * s, 12 * s), Qt.AlignLeft | Qt.AlignVCenter, f"{done}/{total}")

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

    # -- 텍스트 -------------------------------------------------------------
    def _on_text(self):
        self.note["text"] = self.edit.toPlainText()
        self._saved = False
        self._save_timer.start()
        done = ns.progress(self.note["text"])[0]
        if done > self._last_done:
            self.task_completed.emit(self.note["id"])
        self._last_done = done
        self.update()

    def _flush(self):
        self.store.update(self.note["id"], text=self.note["text"], open=self.is_open())
        self._saved = self.store.save()
        self.update()

    def flush_now(self):
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._flush()

    def focus_edit(self):
        if self.is_open():
            self.activateWindow()
            self.raise_()
            self.edit.setFocus()

    # -- 펼치기 / 접기 ------------------------------------------------------
    def _fade(self):
        self.setWindowOpacity(0.35)
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(150)
        self._anim.setStartValue(0.35)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def set_open(self, value):
        if bool(value) == self.is_open():
            return
        self.store.update(self.note["id"], open=bool(value))
        self.apply_layout()
        self._fade()
        self.layout_changed.emit(self.note["id"])
        if value:
            self.focus_edit()
        else:
            self.flush_now()

    def open_full(self):
        self.set_open(True)

    def collapse(self):
        self.set_open(False)

    def toggle(self):
        self.set_open(not self.is_open())

    def set_color(self, color):
        self.store.update(self.note["id"], color=color)
        self.store.save()
        self.update()
        self.layout_changed.emit(self.note["id"])

    def clear_text(self):
        self.edit.setPlainText("")

    # -- 마우스 -------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._menu()
            return
        if e.button() != Qt.LeftButton:
            return
        self._press_btn = None
        if self.is_open():
            for name, rect in self.buttons().items():
                if rect.contains(QPointF(e.pos())):
                    self._press_btn = name

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        btn, self._press_btn = self._press_btn, None
        if not self.is_open():
            if self.note_rect().adjusted(-6, -6, 6, 6).contains(QPointF(e.pos())):
                self.open_full()                                   # 쪽지를 누르면 펼침
        elif btn == "color":
            self._menu(colors_only=True)
        elif btn == "collapse":
            self.collapse()
        elif btn == "clear":
            if time.monotonic() < self._confirm_until:            # 한 번 더 눌러야 지움
                self._confirm_until = 0.0
                self.clear_text()
            else:
                self._confirm_until = time.monotonic() + 3.0
                self.update()
                QTimer.singleShot(3100, self.update)

    def _menu(self, colors_only=False):
        m = QMenu(self)
        cm = m if colors_only else m.addMenu("색상")
        for key, label in ns.COLOR_LABELS.items():
            a = cm.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.note["color"] == key)
            a.triggered.connect(lambda _=False, k=key: self.set_color(k))
        if not colors_only:
            m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)
            m.addSeparator()
            m.addAction("내용 지우기").triggered.connect(self.clear_text)
        m.exec_(QCursor.pos())
