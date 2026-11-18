"""포스트잇 — 폴드 메모 영상의 노트를 캐릭터가 머리 위로 들고 다닌다.

  * 접힌 모습: 머리 위의 작은 쪽지(제목 + 진행률). 누르면 펼쳐진다.
  * 펼친 모습: 제목·본문을 쓰는 정사각형 노트. '–' 버튼이나 Esc 로 다시 접는다.
  * Ctrl+Enter 로 체크리스트, 항목 앞의 ☐ 를 누르면 완료(취소선).  내용은 자동 저장.
"""
import time

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QPen, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QMenu, QTextEdit

import notes_store as ns
from carried import HEADER_H, CarriedItem, make_font


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


class PostIt(CarriedItem):
    task_completed = pyqtSignal(str)          # 체크 항목을 완료함 → 캐릭터가 기뻐함

    def __init__(self, note, store, on_top=True):
        super().__init__(on_top)
        self.note, self.store = note, store
        self._open = bool(note.get("open"))
        self._saved = True
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

    # -- 공통 기반이 부르는 부분 ----------------------------------------------
    def accent(self):
        return QColor(ns.COLORS[self.note["color"]])

    def _store_open(self, value):
        self._open = bool(value)
        self.store.update(self.note["id"], open=self._open)

    def on_layout(self, r):
        if self.is_open():
            self.edit.setGeometry(int(r.x() + 8), int(r.y() + HEADER_H), int(r.width() - 16), int(r.height() - HEADER_H - 22))
            self.edit.show()
        else:
            self.edit.hide()

    def opened_changed(self, is_open):
        if is_open:
            self.focus_edit()
        else:
            self.flush_now()

    def extra_buttons(self):
        r = self.note_rect()
        return {"color": QRectF(r.x() + 6, r.y() + 5, 20, 20), "clear": QRectF(r.right() - 48, r.y() + 5, 20, 20)}

    def progress(self):
        return ns.progress(self.note.get("text", ""))

    # -- 그리기 -------------------------------------------------------------
    def paint_open(self, p, r, base):
        b = self.buttons()
        p.setPen(Qt.NoPen)
        p.setBrush(base.darker(125))
        p.drawEllipse(b["color"].center(), 6, 6)                  # 색 바꾸기
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

    def paint_mini(self, p, r, base):
        from PyQt5.QtGui import QPainterPath
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

    def set_color(self, color):
        self.store.update(self.note["id"], color=color)
        self.store.save()
        self.update()
        self.layout_changed.emit(self)

    def clear_text(self):
        self.edit.setPlainText("")

    # -- 버튼·메뉴 ----------------------------------------------------------
    def button_clicked(self, name):
        if name == "color":
            self._color_menu(self)
        elif name == "clear":
            if time.monotonic() < self._confirm_until:            # 한 번 더 눌러야 지움
                self._confirm_until = 0.0
                self.clear_text()
            else:
                self._confirm_until = time.monotonic() + 3.0
                self.update()
                QTimer.singleShot(3100, self.update)

    def _color_menu(self, parent, into=None):
        m = into or QMenu(parent)
        for key, label in ns.COLOR_LABELS.items():
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.note["color"] == key)
            a.triggered.connect(lambda _=False, k=key: self.set_color(k))
        if into is None:
            m.exec_(QCursor.pos())

    def build_menu(self, m):
        self._color_menu(self, m.addMenu("색상"))
        m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)
        m.addSeparator()
        m.addAction("내용 지우기").triggered.connect(self.clear_text)
