"""포스트잇 — 폴드 메모의 포스트잇을 캐릭터가 머리 위로 들고 다닌다.

  * 접힌 모습: 머리 위의 알약 막대(제목 + 완료/전체). 한 번 누르면 펼쳐지고, 더블클릭하면 이름을 바꾼다.
  * 펼친 모습: 머리줄(제목 · 색 바꾸기 · 내용 지우기 · 접기) + 카드형 편집 영역. Esc 로도 접는다.
  * 제목은 첫 줄에서 자동으로 만들고(최대 20자), 직접 지으면 그 이름을 유지한다.
  * Ctrl+Enter = 현재 줄의 ☐ → ☑ → ☐ 전환, 줄 머리의 ☐ 를 누르면 바로 체크/해제.  내용은 자동 저장.
"""
import re
import time

from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QCursor, QFont, QFontMetrics, QIcon, QPainter, QPixmap, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PyQt5.QtWidgets import QFontDialog, QInputDialog, QLineEdit, QMenu, QPushButton, QTextEdit

import notes_store as ns
from carried import HEADER_H, CarriedItem, make_font, paper_from


class MemoHighlighter(QSyntaxHighlighter):
    """완료(☑) 줄은 취소선 + 흐린 글자."""

    def __init__(self, doc):
        super().__init__(doc)
        self.muted = QColor("#8a8578")

    def highlightBlock(self, text):
        if text.startswith(ns.CHECKED):
            f = QTextCharFormat()
            f.setFontStrikeOut(True)
            f.setForeground(self.muted)
            self.setFormat(1, max(0, len(text) - 1), f)


class MemoEdit(QTextEdit):
    escape_pressed = pyqtSignal()
    save_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.highlighter = MemoHighlighter(self.document())
        self.apply_paper(paper_from(QColor("#FCEB9C")))

    def apply_paper(self, paper):
        t, m = paper["text"], paper["muted"]
        self.setStyleSheet(
            f"QTextEdit{{background:transparent;color:{t.name()};selection-background-color:rgba(120,120,120,70);}}"
            "QScrollBar:vertical{width:6px;background:transparent;}"
            "QScrollBar::handle:vertical{background:rgba(0,0,0,50);border-radius:3px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}")
        self.highlighter.muted = m
        self.highlighter.rehighlight()

    @staticmethod
    def _has_box(text):
        return text[:1] in (ns.UNCHECKED, ns.CHECKED)

    def toggle_box_at(self, cur):
        """줄 머리의 ☐ / ☑ 만 바꾼다(없는 줄은 건드리지 않음)."""
        text = cur.block().text()
        if not self._has_box(text):
            return
        mark = ns.UNCHECKED if text[0] == ns.CHECKED else ns.CHECKED
        cur.beginEditBlock()
        cur.setPosition(cur.block().position())
        cur.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
        cur.insertText(mark)
        cur.endEditBlock()

    def toggle_checklist(self):
        """Ctrl+Enter: 현재 줄을 ☐ → ☑ → ☐ 로 바꾸고, 체크박스가 없으면 '☐ ' 를 붙인다(폴드 메모와 같음)."""
        cur = self.textCursor()
        block = cur.block()
        new = ns.toggle_checklist_line(block.text())
        cur.beginEditBlock()
        cur.setPosition(block.position())
        cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        cur.insertText(new)
        cur.endEditBlock()
        cur.movePosition(QTextCursor.EndOfBlock)
        self.setTextCursor(cur)

    # -- 서식 줄(폴드 메모의 글꼴·제목·목록·B·I·S·링크)이 쓰는 마크다운 도우미 --------------
    def wrap_selection(self, marker, close=None):
        """선택한 글자를 marker 로 감싼다(이미 감싸져 있으면 벗긴다). 선택이 없으면 한 쌍을 넣고 가운데에 커서를 둔다.
        감싼 뒤에도 그 글자를 선택한 채로 두어, 같은 버튼을 다시 누르면 바로 벗겨진다."""
        close = close or marker
        cur = self.textCursor()
        sel = cur.selectedText()
        start = min(cur.position(), cur.anchor())
        cur.beginEditBlock()
        if sel:
            if len(sel) >= len(marker) + len(close) and sel.startswith(marker) and sel.endswith(close):
                out = sel[len(marker):len(sel) - len(close)]
            else:
                out = marker + sel + close
            cur.insertText(out)
            cur.setPosition(start)
            cur.setPosition(start + len(out), QTextCursor.KeepAnchor)
        else:
            pos = cur.position()
            cur.insertText(marker + close)
            cur.setPosition(pos + len(marker))
        cur.endEditBlock()
        self.setTextCursor(cur)

    def _replace_current_line(self, fn):
        cur = self.textCursor()
        block = cur.block()
        cur.beginEditBlock()
        cur.setPosition(block.position())
        cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        cur.insertText(fn(block.text()))
        cur.endEditBlock()
        cur.movePosition(QTextCursor.EndOfBlock)
        self.setTextCursor(cur)

    def set_heading(self, level):
        """현재 줄을 '# ' / '## ' / '### ' 제목으로(같은 단계를 다시 고르면 해제)."""
        prefix = "#" * level + " "

        def fn(line):
            body = re.sub(r"^#{1,6}\s+", "", line)
            return body if line.startswith(prefix) else prefix + body
        self._replace_current_line(fn)

    def toggle_list(self, kind):
        """kind: 'bullet'(- ) / 'number'(1. ). 이미 같은 목록이면 해제."""
        def fn(line):
            plain = re.sub(r"^(\s*)(- |\* |• |\d+[.)]\s+)", r"\1", line)
            if kind == "bullet":
                return plain if re.match(r"^\s*(- |\* |• )", line) else "- " + plain.lstrip()
            return plain if re.match(r"^\s*\d+[.)]\s+", line) else "1. " + plain.lstrip()
        self._replace_current_line(fn)

    def insert_link(self, url):
        cur = self.textCursor()
        text = cur.selectedText() or "링크"
        cur.insertText(f"[{text}]({url})")
        self.setTextCursor(cur)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        ctrl = bool(e.modifiers() & Qt.ControlModifier) and not (e.modifiers() & (Qt.AltModifier | Qt.ShiftModifier))
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.toggle_checklist()
            return
        if ctrl and e.key() == Qt.Key_S:
            self.save_requested.emit()
            return
        if ctrl and e.key() == Qt.Key_B:
            self.wrap_selection("**")
            return
        if ctrl and e.key() == Qt.Key_I:
            self.wrap_selection("*")
            return
        if ctrl and e.key() == Qt.Key_U:
            self.wrap_selection("__")
            return
        super().keyPressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() == Qt.LeftButton and not self.textCursor().hasSelection():
            cur = self.cursorForPosition(e.pos())
            if self._has_box(cur.block().text()) and cur.positionInBlock() <= 1 and e.pos().x() < 30:
                self.toggle_box_at(cur)                           # 누르면 완료 표시


class PostIt(CarriedItem):
    task_completed = pyqtSignal(str)          # 체크 항목을 완료함 → 캐릭터가 기뻐함
    DOUBLE_CLICK_RENAME = True

    def __init__(self, note, store, on_top=True):
        super().__init__(on_top)
        self.note, self.store = note, store
        self._open = bool(note.get("open"))
        self._saved = True
        self._confirm_until = 0.0
        self._want_focus = False
        self._rename_pending = False
        self._last_done = ns.progress(note.get("text", ""))[0]
        self.edit = MemoEdit(self)
        self.edit.setPlainText(note.get("text", ""))
        self.edit.textChanged.connect(self._on_text)
        self.edit.escape_pressed.connect(self.collapse)
        self.edit.save_requested.connect(self.save_now)
        self._fmt_defs = [("font", "글꼴", 1.5), ("heading", "제목", 1.5), ("list", "목록", 1.5), ("bold", "B", 1.0),
                          ("italic", "I", 1.0), ("strike", "S", 1.0), ("link", "링크", 1.5), ("save", "저장", 1.6)]
        self.fmt = {}
        for key, label, _w in self._fmt_defs:
            b = QPushButton(label, self)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.hide()
            b.clicked.connect(lambda _=False, k=key: self._fmt_clicked(k))
            self.fmt[key] = b
        self.title_edit = QLineEdit(self)
        self.title_edit.hide()
        self.title_edit.returnPressed.connect(self._finish_rename)
        self.title_edit.editingFinished.connect(self._finish_rename)
        self.rename_requested.connect(self.begin_rename)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(450)
        self._save_timer.timeout.connect(self._flush)
        self._apply_edit_style()
        self.init_progress()
        self.apply_layout()

    # -- 종이 · 크기 --------------------------------------------------------
    def accent(self):
        return QColor(*ns.COLOR_RGB[self.note["color"]])

    def paper(self):
        return paper_from(self.accent(), dark=self.note["color"] == "graphite")

    def open_size(self):
        return float(self.note["width"]), float(self.note["height"])

    def title_text(self):
        return ns.display_title(self.note)

    def _pill_font(self):
        return make_font(max(6.0, 8.5 * self.mscale), True)

    def mini_size(self):
        s = self.mscale
        fm = QFontMetrics(self._pill_font())
        title = self.title_text() or "새 포스트잇"
        done, total = self.progress()
        prog_w = fm.horizontalAdvance(f"{done}/{total}") + 10 * s if total else 0
        w = fm.horizontalAdvance(title) + prog_w + 36 * s
        return max(96 * s, min(230 * s, w)), 30 * s

    def mini_radius(self):
        return self.mini_size()[1] / 2.0

    def progress(self):
        return ns.progress(self.note.get("text", ""))

    def _apply_edit_style(self):
        paper = self.paper()
        self.edit.apply_paper(paper)
        f = make_font(float(self.note["font_size"]) * 0.95, bool(self.note["bold"]), bool(self.note["italic"]))
        if self.note.get("font_family"):
            f.setFamily(self.note["font_family"])
            if hasattr(f, "setFamilies"):
                f.setFamilies([self.note["font_family"]] + [x for x in f.families() if x != self.note["font_family"]])
        self.edit.setFont(f)
        self.title_edit.setFont(make_font(10, True))
        dark = paper["dark"]
        bg = "rgba(255,255,255,30)" if dark else "rgba(255,255,255,150)"
        hov = "rgba(255,255,255,55)" if dark else "rgba(255,255,255,235)"
        bd = "rgba(255,255,255,40)" if dark else "rgba(0,0,0,38)"
        qss = (f"QPushButton{{background:{bg};color:{paper['text'].name()};border:1px solid {bd};border-radius:9px;"
               f"padding:0 2px;font-size:11px;}}QPushButton:hover{{background:{hov};}}"
               "QPushButton#fmt_save{background:#6C7BF0;color:white;border:none;font-weight:bold;}"
               "QPushButton#fmt_save:hover{background:#5968de;}")
        for key, b in self.fmt.items():
            b.setObjectName("fmt_" + key)
            b.setStyleSheet(qss)
            if key == "bold":
                b.setFont(make_font(8.5, True))
            elif key == "italic":
                b.setFont(make_font(8.5, False, True))
            elif key == "strike":
                f = make_font(8.5)
                f.setStrikeOut(True)
                b.setFont(f)
        self.title_edit.setStyleSheet(
            f"QLineEdit{{background:{paper['card'].name()};color:{paper['text'].name()};border:1px solid rgba(0,0,0,40);"
            "border-radius:6px;padding:1px 6px;}")

    # -- 배치 ---------------------------------------------------------------
    def extra_buttons(self):
        return {"clear": self.header_button(1), "color": self.header_button(2)}

    def draw_extra_icon(self, p, name, rect, color):
        if name == "clear":
            confirm = time.monotonic() < self._confirm_until
            self.draw_icon(p, "close", rect, QColor("#D64545") if confirm else color)
        elif name == "color":
            self.draw_icon(p, "note", rect, color)

    def _title_rect(self, r):
        left = r.x() + 14
        right = self.header_button(2).left() - 6
        return QRectF(left, r.y() + 6, max(40.0, right - left), HEADER_H - 12)

    FMT_H = 24

    def _fmt_rect(self, r):
        return QRectF(r.x() + 10, r.y() + HEADER_H, r.width() - 20, self.FMT_H)

    def _edit_rect(self, r):
        top = HEADER_H + self.FMT_H + 6
        return QRectF(r.x() + 12, r.y() + top, r.width() - 24, r.height() - top - 26)

    def on_layout(self, r, show):
        if show:
            er = self._edit_rect(r)
            self.edit.setGeometry(int(er.x() + 8), int(er.y() + 6), int(er.width() - 16), int(er.height() - 12))
            tr = self._title_rect(r)
            self.title_edit.setGeometry(int(tr.x()), int(tr.y()), int(tr.width()), int(tr.height()))
            fr = self._fmt_rect(r)                                  # 서식 줄: 글꼴·제목·목록·B·I·S·링크·저장
            gap = 3
            total = sum(w for _k, _l, w in self._fmt_defs)
            unit = (fr.width() - gap * (len(self._fmt_defs) - 1)) / total
            x = fr.x()
            for key, _label, w in self._fmt_defs:
                self.fmt[key].setGeometry(int(round(x)), int(fr.y()), int(round(unit * w)), int(fr.height()))
                self.fmt[key].show()
                x += unit * w + gap
            if not self.edit.isVisible():
                self.edit.show()
                if self._want_focus:
                    self._want_focus = False
                    self.focus_edit()
                if self._rename_pending:
                    self._rename_pending = False
                    self.begin_rename()
        else:
            self.edit.hide()
            self.title_edit.hide()
            for b in self.fmt.values():
                b.hide()

    # -- 그리기 -------------------------------------------------------------
    def paint_open(self, p, r, paper):
        tr = self._title_rect(r)
        if not self.title_edit.isVisible():
            title = self.title_text()
            p.setPen(paper["text"] if title else paper["muted"])
            f = make_font(10.5, True)
            p.setFont(f)
            p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter,
                       QFontMetrics(f).elidedText(title or "새 포스트잇", Qt.ElideRight, int(tr.width())))
        er = self._edit_rect(r)                           # 종이보다 22% 밝은 카드
        p.setPen(Qt.NoPen)
        p.setBrush(paper["card"])
        p.drawRoundedRect(er, 10, 10)
        p.setPen(paper["muted"])
        p.setFont(make_font(7.5))
        p.drawText(QRectF(r.x() + 16, r.bottom() - 24, 90, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "저장됨" if self._saved else "저장 중…")
        done, total = self.progress()
        if total:
            p.drawText(QRectF(r.right() - 76, r.bottom() - 24, 60, 18), Qt.AlignRight | Qt.AlignVCenter, f"{done}/{total}")

    def paint_mini(self, p, r, paper):
        s = self.mscale
        title = self.title_text()
        done, total = self.progress()
        f = self._pill_font()
        p.setFont(f)
        right = 12 * s
        if total:
            p.setPen(paper["muted"])
            w = QFontMetrics(f).horizontalAdvance(f"{done}/{total}")
            p.drawText(QRectF(r.right() - right - w - 4, r.y(), w + 4, r.height()), Qt.AlignRight | Qt.AlignVCenter, f"{done}/{total}")
            right += w + 10 * s
        tr = QRectF(r.x() + 14 * s, r.y(), max(10.0, r.width() - 14 * s - right), r.height())
        p.setPen(paper["text"] if title else paper["muted"])
        p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter, QFontMetrics(f).elidedText(title or "새 포스트잇", Qt.ElideRight, int(tr.width())))

    # -- 텍스트 -------------------------------------------------------------
    def _on_text(self):
        self.note["text"] = self.edit.toPlainText()
        if not self.note.get("title_manual"):
            self.note["title"] = ns.derived_title(self.note["text"])
        self._saved = False
        self._save_timer.start()
        done = ns.progress(self.note["text"])[0]
        if done > self._last_done:
            self.task_completed.emit(self.note["id"])
        self._last_done = done
        if not self.is_open() and not self.animating():        # 접힌 알약은 제목·진행률에 따라 폭이 변한다
            self.apply_layout()
        self.update()

    def _flush(self):
        self.store.update(self.note["id"], text=self.note["text"], title=self.note.get("title", ""),
                          title_manual=bool(self.note.get("title_manual")), open=self.is_open())
        self._saved = self.store.save()
        self.update()

    def flush_now(self):
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._flush()

    def save_now(self):
        """저장 버튼 / Ctrl+S: 바로 저장하고 잠깐 '저장됨 ✓' 로 알려 준다."""
        self.flush_now()
        b = self.fmt["save"]
        b.setText("저장됨 ✓")
        QTimer.singleShot(1200, lambda: b.setText("저장"))
        self.update()

    def _fmt_clicked(self, key):
        ed = self.edit
        if key == "font":
            self.pick_font()
        elif key == "heading":
            m = QMenu(self)
            for lv, label in ((1, "제목 1  (# )"), (2, "제목 2  (## )"), (3, "제목 3  (### )")):
                m.addAction(label).triggered.connect(lambda _=False, v=lv: ed.set_heading(v))
            m.exec_(QCursor.pos())
        elif key == "list":
            m = QMenu(self)
            m.addAction("• 글머리 기호").triggered.connect(lambda: ed.toggle_list("bullet"))
            m.addAction("1. 번호 목록").triggered.connect(lambda: ed.toggle_list("number"))
            m.addAction("☐ 체크리스트  (Ctrl+Enter)").triggered.connect(ed.toggle_checklist)
            m.exec_(QCursor.pos())
        elif key == "bold":
            ed.wrap_selection("**")
        elif key == "italic":
            ed.wrap_selection("*")
        elif key == "strike":
            ed.wrap_selection("~~")
        elif key == "link":
            url, ok = QInputDialog.getText(self, "링크", "주소(URL)", text="https://")
            if ok and url.strip():
                ed.insert_link(url.strip())
        elif key == "save":
            self.save_now()
        ed.setFocus()

    def pick_font(self):
        """글꼴 창: 글꼴·크기·굵게·기울임을 한 번에 고른다(포스트잇 전체에 적용)."""
        cur = self.edit.font()
        font, ok = QFontDialog.getFont(cur, self, "글꼴")
        if ok:
            self.apply_font(font.family(), font.pointSizeF() / 0.95, font.bold(), font.italic())

    def apply_font(self, family, size, bold, italic):
        self.note["font_family"] = family or ""
        self.note["font_size"] = max(8.0, min(24.0, float(size)))
        self.note["bold"], self.note["italic"] = bool(bold), bool(italic)
        self.store.update(self.note["id"], font_family=self.note["font_family"])
        self._commit_style()

    def focus_edit(self):
        if self.is_open() and self.edit.isVisible():
            self.activateWindow()
            self.raise_()
            self.edit.setFocus()

    def opened_changed(self, is_open):
        if is_open:
            self._want_focus = True
            if not SETTINGS_ANIMATE():
                self.focus_edit()
        else:
            self.title_edit.hide()
            self.flush_now()

    # -- 이름 바꾸기 --------------------------------------------------------
    def begin_rename(self):
        if not self.is_open():
            self._rename_pending = True
            self.open_full()
            return
        if not self.edit.isVisible():
            self._rename_pending = True
            return
        self.title_edit.setText(self.title_text())
        self.title_edit.show()
        self.title_edit.raise_()
        self.activateWindow()
        self.title_edit.setFocus()
        self.title_edit.selectAll()

    def _finish_rename(self):
        if not self.title_edit.isVisible():
            return
        name = self.title_edit.text().strip()
        self.title_edit.hide()
        if name:
            self.note["title"], self.note["title_manual"] = name, True      # 직접 지은 이름은 그대로 유지
        else:
            self.note["title_manual"] = False                               # 비우면 다시 자동 제목
            self.note["title"] = ns.derived_title(self.note.get("text", ""))
        self.flush_now()
        if not self.is_open() and not self.animating():
            self.apply_layout()
        self.update()
        self.layout_changed.emit(self)

    # -- 꾸미기 -------------------------------------------------------------
    def _commit_style(self):
        self.store.update(self.note["id"], color=self.note["color"], width=self.note["width"], height=self.note["height"],
                          font_size=self.note["font_size"], bold=self.note["bold"], italic=self.note["italic"])
        self.store.save()
        self._apply_edit_style()
        self.apply_layout()
        self.layout_changed.emit(self)

    def set_color(self, color):
        if color in ns.COLOR_RGB:
            self.note["color"] = color
            self._commit_style()

    def next_color(self):
        names = ns.COLOR_NAMES
        self.set_color(names[(names.index(self.note["color"]) + 1) % len(names)])

    def set_size(self, w, h):
        self.note["width"] = max(ns.MIN_W, min(ns.MAX_W, int(w)))
        self.note["height"] = max(ns.MIN_H, min(ns.MAX_H, int(h)))
        self._commit_style()

    def set_font_size(self, pt):
        self.note["font_size"] = max(8.0, min(24.0, float(pt)))
        self._commit_style()

    def toggle_bold(self):
        self.note["bold"] = not self.note["bold"]
        self._commit_style()

    def clear_text(self):
        self.edit.setPlainText("")

    # -- 버튼·메뉴 ----------------------------------------------------------
    def button_clicked(self, name):
        if name == "color":
            self.next_color()                                   # 폴드 메모처럼 누를 때마다 다음 색
        elif name == "clear":
            if time.monotonic() < self._confirm_until:          # 한 번 더 눌러야 지움
                self._confirm_until = 0.0
                self.clear_text()
            else:
                self._confirm_until = time.monotonic() + 3.0
                self.update()
                QTimer.singleShot(3100, self.update)

    @staticmethod
    def _swatch(rgb):
        pm = QPixmap(14, 14)
        pm.fill(Qt.transparent)
        pt = QPainter(pm)
        pt.setRenderHint(QPainter.Antialiasing)
        pt.setPen(QColor(0, 0, 0, 60))
        pt.setBrush(QColor(*rgb))
        pt.drawRoundedRect(QRectF(1, 1, 12, 12), 3, 3)
        pt.end()
        return QIcon(pm)

    def build_menu(self, m):
        m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)
        m.addAction("이름 바꾸기").triggered.connect(self.begin_rename)
        m.addSeparator()
        cm = m.addMenu("색 바꾸기")
        for key in ns.COLOR_NAMES:
            a = cm.addAction(self._swatch(ns.COLOR_RGB[key]), ns.COLOR_LABELS[key])
            a.setCheckable(True)
            a.setChecked(self.note["color"] == key)
            a.triggered.connect(lambda _=False, k=key: self.set_color(k))
        sm = m.addMenu("크기")
        for label, (w, h) in ns.SIZES.items():
            sm.addAction(f"{label}  ({w}×{h})").triggered.connect(lambda _=False, a=w, b=h: self.set_size(a, b))
        fm = m.addMenu("글자 크기")
        for label, pt in (("작게", 10), ("보통", 11), ("크게", 13), ("아주 크게", 15)):
            a = fm.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.note["font_size"] - pt) < 0.5)
            a.triggered.connect(lambda _=False, v=pt: self.set_font_size(v))
        b = m.addAction("굵게")
        b.setCheckable(True)
        b.setChecked(bool(self.note["bold"]))
        b.triggered.connect(self.toggle_bold)
        m.addSeparator()
        m.addAction("체크 전환 (Ctrl+Enter)").triggered.connect(lambda: (self.open_full(), self.edit.toggle_checklist()))
        m.addAction("내용 지우기").triggered.connect(self.clear_text)


def SETTINGS_ANIMATE():
    from carried import SETTINGS
    return bool(SETTINGS["animate"])
