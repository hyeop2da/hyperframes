"""포스트잇 — 폴드 메모의 포스트잇을 캐릭터가 머리 위로 들고 다닌다.

  * 접힌 모습: 머리 위의 알약 막대(제목 + 완료/전체). 한 번 누르면 펼쳐지고, 더블클릭하면 이름을 바꾼다.
  * 펼친 모습: 머리줄(제목 · 색 바꾸기 · 내용 지우기 · 접기) + 서식 줄 + 카드형 편집 영역. Esc 로도 접는다.
  * 서식 줄: 글꼴 · 제목 · 목록 · B · I · S · 링크.  글자를 선택하고 오른쪽 클릭 → 글꼴을 고르면 **선택한 부분에만** 바뀐다.
  * 제목은 첫 줄에서 자동으로 만들고(최대 20자), 직접 지으면 그 이름을 유지한다.
  * Ctrl+Enter = 현재 줄의 ☐ → ☑ → ☐ 전환, 줄 머리의 ☐ 를 누르면 바로 체크/해제.  내용과 서식은 자동 저장.
"""
import re
import time

from PyQt5.QtCore import QRectF, QUrl, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (
    QColor, QCursor, QDesktopServices, QFont, QFontMetrics, QIcon, QPainter, QPixmap, QSyntaxHighlighter,
    QTextCharFormat, QTextCursor, QTextFormat,
)
from PyQt5.QtWidgets import QAction, QFontDialog, QInputDialog, QLineEdit, QMenu, QPushButton, QTextEdit, QToolTip

import notes_store as ns
from carried import HEADER_H, CarriedItem, make_font, paper_from

HEADING_SCALE = {1: 1.7, 2: 1.4, 3: 1.2}                       # 폴드 메모와 같은 제목 배율
_LINE_PREFIX = re.compile(r"^(\s*)(#{1,6}\s+|[-*•]\s+|\d+[.)]\s+|☐\s?|☑\s?)")


class MemoHighlighter(QSyntaxHighlighter):
    """완료(☑) 줄은 취소선 + 흐린 글자(저장되는 서식과는 별개의 보기 효과)."""

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
    link_requested = pyqtSignal()
    font_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setFrameShape(QTextEdit.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.highlighter = MemoHighlighter(self.document())
        self.base = ("", 10.45, False, False)           # (글꼴, 크기pt, 굵게, 기울임): 포스트잇 전체 글꼴
        self.link_color = QColor("#2B6CB0")
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
        self.link_color = QColor("#7FB2FF") if paper.get("dark") else QColor("#2B6CB0")
        self.recolor_links()

    def setPlainText(self, text):
        """새 글을 넣을 때 이전 글자의 서식이 따라 붙지 않게 문서를 비우고 시작한다."""
        self.document().clear()
        self.setCurrentCharFormat(QTextCharFormat())
        super().setPlainText(text)

    def contextMenuEvent(self, e):
        self.build_context_menu().exec_(e.globalPos())

    def build_context_menu(self):
        """오른쪽 클릭: 글자를 선택해 두었으면 그 부분만 글꼴·굵게·기울임·취소선을 바꾼다."""
        m = self.createStandardContextMenu()
        m.setParent(self, m.windowFlags())              # 메뉴가 바로 사라지지 않게 편집창에 매단다
        if self.textCursor().hasSelection():
            first = m.actions()[0] if m.actions() else None
            acts = []
            a = QAction("선택한 글자 글꼴…", m)
            a.triggered.connect(self.font_requested.emit)
            acts.append(a)
            bold, ital, strike = self.style_state()
            for label, kind, on in (("굵게", "bold", bold), ("기울임", "italic", ital), ("취소선", "strike", strike)):
                b = QAction(label, m)
                b.setCheckable(True)
                b.setChecked(on)
                b.triggered.connect(lambda _=False, k=kind: self.toggle_style(k))
                acts.append(b)
            c = QAction("선택한 글자 서식 지우기", m)
            c.triggered.connect(self.clear_selection_format)
            acts.append(c)
            sep = QAction(m)
            sep.setSeparator(True)
            acts.append(sep)
            m.insertActions(first, acts)
        return m

    def insertFromMimeData(self, source):
        """붙여넣기는 글자만(다른 곳의 서식은 가져오지 않는다)."""
        if source.hasText():
            self.insertPlainText(source.text())

    # -- 체크리스트 ----------------------------------------------------------
    @staticmethod
    def _has_box(text):
        return text[:1] in (ns.UNCHECKED, ns.CHECKED)

    def _replace_first_char(self, cur, mark):
        cur.setPosition(cur.block().position())
        cur.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor)
        cur.insertText(mark)

    def toggle_box_at(self, cur):
        """줄 머리의 ☐ / ☑ 만 바꾼다(없는 줄은 건드리지 않음). 줄의 서식은 그대로 둔다."""
        text = cur.block().text()
        if not self._has_box(text):
            return
        cur.beginEditBlock()
        self._replace_first_char(cur, ns.UNCHECKED if text[0] == ns.CHECKED else ns.CHECKED)
        cur.endEditBlock()

    def toggle_checklist(self):
        """Ctrl+Enter: 현재 줄을 ☐ → ☑ → ☐ 로 바꾸고, 체크박스가 없으면 '☐ ' 를 붙인다(폴드 메모와 같음)."""
        cur = self.textCursor()
        text = cur.block().text()
        cur.beginEditBlock()
        if self._has_box(text):
            self._replace_first_char(cur, ns.UNCHECKED if text[0] == ns.CHECKED else ns.CHECKED)
        else:
            cur.setPosition(cur.block().position())
            cur.insertText(ns.UNCHECKED + " ")
        cur.endEditBlock()
        cur.movePosition(QTextCursor.EndOfBlock)
        self.setTextCursor(cur)

    # -- 글자 서식(선택한 부분에만) -------------------------------------------
    def _first_selected_format(self):
        cur = self.textCursor()
        if cur.hasSelection():
            probe = QTextCursor(self.document())
            probe.setPosition(min(cur.position(), cur.anchor()) + 1)        # 선택한 첫 글자의 서식
            return probe.charFormat()
        return self.currentCharFormat()

    def effective(self, fmt):
        """서식에 따로 정해 둔 값이 없으면 포스트잇 전체 글꼴 값을 쓴다 → (글꼴, 크기, 굵게, 기울임, 취소선, 밑줄)."""
        fam, pt, bold, ital = self.base
        if fmt.hasProperty(QTextFormat.FontFamily):
            fam = fmt.fontFamily()
        if fmt.hasProperty(QTextFormat.FontPointSize):
            pt = fmt.fontPointSize()
        if fmt.hasProperty(QTextFormat.FontWeight):
            bold = fmt.fontWeight() >= QFont.Bold
        if fmt.hasProperty(QTextFormat.FontItalic):
            ital = fmt.fontItalic()
        return fam, pt, bool(bold), bool(ital), fmt.fontStrikeOut(), fmt.fontUnderline()

    def _merge(self, fmt):
        cur = self.textCursor()
        if cur.hasSelection():
            cur.mergeCharFormat(fmt)
            self.setTextCursor(cur)
        else:
            self.mergeCurrentCharFormat(fmt)            # 선택이 없으면 이어서 쓰는 글자에 적용

    def toggle_style(self, kind):
        """B / I / S / U: 선택한 글자의 굵기·기울임·취소선·밑줄을 켜고 끈다."""
        _fam, _pt, bold, ital, strike, under = self.effective(self._first_selected_format())
        fmt = QTextCharFormat()
        if kind == "bold":
            fmt.setFontWeight(QFont.Normal if bold else QFont.Bold)
        elif kind == "italic":
            fmt.setFontItalic(not ital)
        elif kind == "strike":
            fmt.setFontStrikeOut(not strike)
        elif kind == "underline":
            fmt.setFontUnderline(not under)
        self._merge(fmt)

    def style_state(self):
        """현재 글자의 (굵게, 기울임, 취소선) — 서식 줄 버튼의 눌림 표시에 쓴다."""
        _f, _p, bold, ital, strike, _u = self.effective(self._first_selected_format())
        return bold, ital, strike

    def selection_font_info(self):
        fam, pt, bold, ital, _s, _u = self.effective(self._first_selected_format())
        return fam or self.font().family(), pt, bold, ital

    def apply_selection_font(self, family, size, bold, italic):
        """글꼴 창에서 고른 값을 선택한 글자에만 적용한다."""
        if not self.textCursor().hasSelection():
            return False
        fmt = QTextCharFormat()
        fmt.setFontFamily(family)
        fmt.setFontPointSize(float(size))
        fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)
        fmt.setFontItalic(bool(italic))
        self._merge(fmt)
        return True

    def clear_selection_format(self):
        cur = self.textCursor()
        if not cur.hasSelection():
            return False
        cur.setCharFormat(QTextCharFormat())            # 선택한 글자를 기본 글꼴로 되돌린다
        self.setTextCursor(cur)
        return True

    def set_heading(self, level):
        """제목 1~3: 현재 줄 전체를 크고 굵게(1.7·1.4·1.2배). 0 = 본문(기본 글꼴로 되돌림)."""
        cur = self.textCursor()
        cur.beginEditBlock()
        cur.setPosition(cur.block().position())
        cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
        if level <= 0:
            cur.setCharFormat(QTextCharFormat())
        else:
            fmt = QTextCharFormat()
            fmt.setFontPointSize(self.base[1] * HEADING_SCALE.get(level, 1.0))
            fmt.setFontWeight(QFont.Bold)
            cur.mergeCharFormat(fmt)
        cur.endEditBlock()

    def heading_level(self):
        pt = self.effective(self.textCursor().block().begin().fragment().charFormat())[1] if not self.textCursor().block().begin().atEnd() else self.base[1]
        for lv, mul in HEADING_SCALE.items():
            if abs(pt - self.base[1] * mul) < 0.3:
                return lv
        return 0

    def apply_line_prefix(self, kind):
        """목록: 선택한 줄들에 글머리(• )·번호(1. )·체크(☐ )를 붙인다. 모두 이미 붙어 있으면 뗀다."""
        cur = self.textCursor()
        doc = self.document()
        first = doc.findBlock(min(cur.position(), cur.anchor()))
        last = doc.findBlock(max(cur.position(), cur.anchor()))
        blocks = []
        b = first
        while b.isValid():
            blocks.append(b)
            if b == last:
                break
            b = b.next()
        have = {"bullet": r"^\s*[-*•]\s", "number": r"^\s*\d+[.)]\s", "check": r"^\s*[☐☑]"}[kind]
        all_have = all(re.match(have, blk.text()) for blk in blocks)
        edit = QTextCursor(doc)
        edit.beginEditBlock()
        for n, blk in reversed(list(enumerate(blocks, 1))):         # 뒤에서부터 고쳐야 앞 줄의 위치가 안 밀린다
            m = _LINE_PREFIX.match(blk.text())
            start = blk.position() + (len(m.group(1)) if m else 0)
            if m:
                edit.setPosition(start)
                edit.setPosition(blk.position() + m.end(), QTextCursor.KeepAnchor)
                edit.removeSelectedText()
            if not all_have:
                edit.setPosition(start)
                edit.insertText({"bullet": "• ", "number": f"{n}. ", "check": ns.UNCHECKED + " "}[kind])
        edit.endEditBlock()

    def insert_link(self, url):
        """링크: 주소를 글에 넣고 눌러 열 수 있는 링크 서식을 입힌다(글자를 선택했으면 그 뒤에 이어 넣는다)."""
        cur = self.textCursor()
        sel = cur.hasSelection()
        end = max(cur.position(), cur.anchor())
        cur.beginEditBlock()
        cur.setPosition(end)
        if sel:
            cur.insertText(" ")
        start = cur.position()
        cur.insertText(url)
        cur.setPosition(start)
        cur.setPosition(start + len(url), QTextCursor.KeepAnchor)
        cur.mergeCharFormat(self._link_format(url))
        cur.endEditBlock()
        cur.setPosition(start + len(url))
        self.setTextCursor(cur)

    def _link_format(self, url):
        fmt = QTextCharFormat()
        fmt.setAnchor(True)
        fmt.setAnchorHref(url)
        fmt.setFontUnderline(True)
        fmt.setForeground(self.link_color)
        return fmt

    def recolor_links(self):
        doc = self.document()
        blk = doc.begin()
        cur = QTextCursor(doc)
        cur.beginEditBlock()
        while blk.isValid():
            it = blk.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid() and frag.charFormat().isAnchor():
                    cur.setPosition(frag.position())
                    cur.setPosition(frag.position() + frag.length(), QTextCursor.KeepAnchor)
                    f = QTextCharFormat()
                    f.setForeground(self.link_color)
                    cur.mergeCharFormat(f)
                it += 1
            blk = blk.next()
        cur.endEditBlock()

    # -- 서식 저장·복원(글자별 구간) -------------------------------------------
    def serialize_runs(self):
        """글자별 서식을 작은 목록으로 뽑는다(포스트잇 전체 글꼴과 같은 값은 저장하지 않는다)."""
        runs = []
        blk = self.document().begin()
        while blk.isValid():
            it = blk.begin()
            while not it.atEnd():
                frag = it.fragment()
                if frag.isValid():
                    r = self._fmt_to_run(frag.charFormat())
                    if r:
                        r["s"], r["n"] = frag.position(), frag.length()
                        if runs and runs[-1]["s"] + runs[-1]["n"] == r["s"] and \
                                {k: v for k, v in runs[-1].items() if k not in ("s", "n")} == {k: v for k, v in r.items() if k not in ("s", "n")}:
                            runs[-1]["n"] += r["n"]
                        else:
                            runs.append(r)
                it += 1
            blk = blk.next()
        return runs

    @staticmethod
    def _fmt_to_run(fmt):
        r = {}
        href = fmt.anchorHref() if fmt.isAnchor() else ""
        if fmt.hasProperty(QTextFormat.FontFamily):
            r["f"] = fmt.fontFamily()
        if fmt.hasProperty(QTextFormat.FontPointSize):
            r["z"] = round(fmt.fontPointSize(), 2)
        if fmt.hasProperty(QTextFormat.FontWeight):
            r["b"] = 1 if fmt.fontWeight() >= QFont.Bold else 0
        if fmt.hasProperty(QTextFormat.FontItalic):
            r["i"] = 1 if fmt.fontItalic() else 0
        if fmt.hasProperty(QTextFormat.FontStrikeOut):
            r["k"] = 1 if fmt.fontStrikeOut() else 0
        if fmt.hasProperty(QTextFormat.FontUnderline) and not href:
            r["u"] = 1 if fmt.fontUnderline() else 0
        if href:
            r["h"] = href
        return r

    def apply_runs(self, runs):
        cur = QTextCursor(self.document())
        cur.beginEditBlock()
        for r in runs or []:
            fmt = QTextCharFormat()
            if r.get("f"):
                fmt.setFontFamily(r["f"])
            if r.get("z"):
                fmt.setFontPointSize(float(r["z"]))
            if "b" in r:
                fmt.setFontWeight(QFont.Bold if r["b"] else QFont.Normal)
            if "i" in r:
                fmt.setFontItalic(bool(r["i"]))
            if "k" in r:
                fmt.setFontStrikeOut(bool(r["k"]))
            if "u" in r:
                fmt.setFontUnderline(bool(r["u"]))
            if r.get("h"):
                fmt = self._link_format(r["h"])
            cur.setPosition(r["s"])
            cur.setPosition(r["s"] + r["n"], QTextCursor.KeepAnchor)
            cur.mergeCharFormat(fmt)
        cur.endEditBlock()

    # -- 키·마우스 -----------------------------------------------------------
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        ctrl = bool(e.modifiers() & Qt.ControlModifier) and not (e.modifiers() & (Qt.AltModifier | Qt.ShiftModifier))
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.toggle_checklist()
            return
        if ctrl:
            handlers = {Qt.Key_S: self.save_requested.emit, Qt.Key_B: lambda: self.toggle_style("bold"),
                        Qt.Key_I: lambda: self.toggle_style("italic"), Qt.Key_U: lambda: self.toggle_style("underline"),
                        Qt.Key_K: self.link_requested.emit}
            if e.key() in handlers:
                handlers[e.key()]()
                return
        super().keyPressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() != Qt.LeftButton:
            return
        if e.modifiers() & Qt.ControlModifier:
            href = self.anchorAt(e.pos())
            if href:
                QDesktopServices.openUrl(QUrl(href))            # Ctrl+클릭으로 링크 열기
                return
        if not self.textCursor().hasSelection():
            cur = self.cursorForPosition(e.pos())
            if self._has_box(cur.block().text()) and cur.positionInBlock() <= 1 and e.pos().x() < 30:
                self.toggle_box_at(cur)                           # 누르면 완료 표시


class PostIt(CarriedItem):
    task_completed = pyqtSignal(str)          # 체크 항목을 완료함 → 캐릭터가 기뻐함
    DOUBLE_CLICK_RENAME = True
    RESIZABLE = True
    FMT_H = 24

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
        self.edit.apply_runs(note.get("runs"))                      # 저장해 둔 글자별 서식을 되살린다
        self.edit.textChanged.connect(self._on_text)
        self.edit.escape_pressed.connect(self.collapse)
        self.edit.save_requested.connect(self.save_now)
        self.edit.link_requested.connect(self.ask_link)
        self.edit.font_requested.connect(self.pick_selection_font)
        self.edit.currentCharFormatChanged.connect(lambda _f: self._sync_fmt_state())
        self.edit.cursorPositionChanged.connect(self._sync_fmt_state)
        self._fmt_defs = [("font", "글꼴", 1.5), ("heading", "제목", 1.5), ("list", "목록", 1.5), ("bold", "B", 1.0),
                          ("italic", "I", 1.0), ("strike", "S", 1.0), ("link", "링크", 1.5)]
        self.fmt = {}
        for key, label, _w in self._fmt_defs:
            b = QPushButton(label, self)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)                         # 눌러도 글자 선택이 풀리지 않게
            if key in ("bold", "italic", "strike"):
                b.setCheckable(True)
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
        pt = float(self.note["font_size"]) * 0.95
        fam = self.note.get("font_family") or ""
        self.edit.base = (fam, pt, bool(self.note["bold"]), bool(self.note["italic"]))
        self.edit.apply_paper(paper)
        f = make_font(pt, bool(self.note["bold"]), bool(self.note["italic"]))
        if fam:
            f.setFamily(fam)
            if hasattr(f, "setFamilies"):
                f.setFamilies([fam] + [x for x in f.families() if x != fam])
        self.edit.setFont(f)
        self.title_edit.setFont(make_font(10, True))
        self.title_edit.setStyleSheet(
            f"QLineEdit{{background:{paper['card'].name()};color:{paper['text'].name()};border:1px solid rgba(0,0,0,40);"
            "border-radius:6px;padding:1px 6px;}")
        dark = paper["dark"]
        bg = "rgba(255,255,255,30)" if dark else "rgba(255,255,255,150)"
        hov = "rgba(255,255,255,55)" if dark else "rgba(255,255,255,235)"
        on = "rgba(255,255,255,90)" if dark else "rgba(255,255,255,255)"
        bd = "rgba(255,255,255,40)" if dark else "rgba(0,0,0,38)"
        bd_on = "rgba(255,255,255,150)" if dark else "rgba(0,0,0,120)"
        qss = (f"QPushButton{{background:{bg};color:{paper['text'].name()};border:1px solid {bd};border-radius:9px;"
               f"padding:0 2px;font-size:11px;}}QPushButton:hover{{background:{hov};}}"
               f"QPushButton:checked{{background:{on};border:1px solid {bd_on};}}"
               "")
        for key, b in getattr(self, "fmt", {}).items():
            b.setObjectName("fmt_" + key)
            b.setStyleSheet(qss)
            if key == "bold":
                b.setFont(make_font(8.5, True))
            elif key == "italic":
                b.setFont(make_font(8.5, False, True))
            elif key == "strike":
                sf = make_font(8.5)
                sf.setStrikeOut(True)
                b.setFont(sf)

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
            fr = self._fmt_rect(r)                                  # 서식 줄: 글꼴·제목·목록·B·I·S·링크
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
                self._sync_fmt_state()
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
        self.note["runs"] = ns._clean_runs(self.edit.serialize_runs(), len(self.note["text"]))
        self.store.update(self.note["id"], text=self.note["text"], title=self.note.get("title", ""),
                          title_manual=bool(self.note.get("title_manual")), open=self.is_open(), runs=self.note["runs"])
        self._saved = self.store.save()
        self.update()

    def flush_now(self):
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._flush()

    def save_now(self):
        """Ctrl+S: 바로 저장한다(평소엔 자동 저장)."""
        self.flush_now()
        self.update()

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

    # -- 서식 줄 ------------------------------------------------------------
    def _sync_fmt_state(self):
        bold, ital, strike = self.edit.style_state()
        for key, val in (("bold", bold), ("italic", ital), ("strike", strike)):
            b = self.fmt.get(key)
            if b is not None and b.isChecked() != val:
                b.blockSignals(True)
                b.setChecked(val)
                b.blockSignals(False)

    def _need_selection(self):
        QToolTip.showText(QCursor.pos(), "글꼴을 바꿀 글자를 먼저 선택하세요.", self)

    def _fmt_clicked(self, key):
        ed = self.edit
        if key == "font":
            if ed.textCursor().hasSelection():                      # 글자를 선택해 두었으면 그 부분만
                self.pick_selection_font()
            else:
                self.pick_note_font()                               # 선택이 없으면 포스트잇 전체 글꼴
        elif key == "heading":
            m = QMenu(self)
            for lv, label in ((1, "제목 1"), (2, "제목 2"), (3, "제목 3"), (0, "본문")):
                m.addAction(label).triggered.connect(lambda _=False, v=lv: ed.set_heading(v))
            m.exec_(QCursor.pos())
        elif key == "list":
            m = QMenu(self)
            m.addAction("• 글머리 기호 목록").triggered.connect(lambda: ed.apply_line_prefix("bullet"))
            m.addAction("1. 번호 목록").triggered.connect(lambda: ed.apply_line_prefix("number"))
            m.addAction("☐ 체크리스트").triggered.connect(lambda: ed.apply_line_prefix("check"))
            m.exec_(QCursor.pos())
        elif key == "bold":
            ed.toggle_style("bold")
        elif key == "italic":
            ed.toggle_style("italic")
        elif key == "strike":
            ed.toggle_style("strike")
        elif key == "link":
            self.ask_link()
        ed.setFocus()
        self._sync_fmt_state()

    def ask_link(self):
        url, ok = QInputDialog.getText(self, "링크 넣기", "링크 주소", text="https://")
        if ok and url.strip() and url.strip() != "https://":
            self.edit.insert_link(url.strip())

    def pick_selection_font(self):
        """글꼴 창: 글꼴·크기·굵게·기울임을 골라 **선택한 글자에만** 적용한다."""
        if not self.edit.textCursor().hasSelection():
            self._need_selection()
            return
        fam, pt, bold, ital = self.edit.selection_font_info()
        cur = QFont(fam)
        cur.setPointSizeF(pt)
        cur.setBold(bold)
        cur.setItalic(ital)
        font, ok = QFontDialog.getFont(cur, self, "글꼴 (선택한 글자)")
        if ok:
            self.edit.apply_selection_font(font.family(), font.pointSizeF(), font.bold(), font.italic())

    def clear_selection_format(self):
        if not self.edit.clear_selection_format():
            QToolTip.showText(QCursor.pos(), "서식을 지울 글자를 먼저 선택하세요.", self)

    def pick_note_font(self):
        """포스트잇 전체 글꼴(서식을 따로 정하지 않은 글자에 적용)."""
        cur = self.edit.font()
        font, ok = QFontDialog.getFont(cur, self, "글꼴 — 선택한 글자가 없어 포스트잇 전체에 적용")
        if ok:
            self.apply_font(font.family(), font.pointSizeF() / 0.95, font.bold(), font.italic())

    def apply_font(self, family, size, bold, italic):
        self.note["font_family"] = family or ""
        self.note["font_size"] = max(8.0, min(24.0, float(size)))
        self.note["bold"], self.note["italic"] = bool(bold), bool(italic)
        self.store.update(self.note["id"], font_family=self.note["font_family"])
        self._commit_style()

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

    def resize_to(self, w, h):
        """끄는 동안: 화면만 바로 바꾼다(저장은 놓을 때)."""
        self.note["width"] = max(ns.MIN_W, min(ns.MAX_W, int(w)))
        self.note["height"] = max(ns.MIN_H, min(ns.MAX_H, int(h)))
        self.apply_layout()
        self.layout_changed.emit(self)

    def resize_done(self):
        self._commit_style()

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
        sm = m.addMenu("크기 (왼쪽 위 모서리를 끌어도 돼요)")
        for label, (w, h) in ns.SIZES.items():
            sm.addAction(f"{label}  ({w}×{h})").triggered.connect(lambda _=False, a=w, b=h: self.set_size(a, b))
        fm = m.addMenu("글자 크기 (전체)")
        for label, pt in (("작게", 10), ("보통", 11), ("크게", 13), ("아주 크게", 15)):
            a = fm.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.note["font_size"] - pt) < 0.5)
            a.triggered.connect(lambda _=False, v=pt: self.set_font_size(v))
        m.addSeparator()
        m.addAction("체크 전환 (Ctrl+Enter)").triggered.connect(lambda: (self.open_full(), self.edit.toggle_checklist()))
        m.addAction("내용 지우기").triggered.connect(self.clear_text)


def SETTINGS_ANIMATE():
    from carried import SETTINGS
    return bool(SETTINGS["animate"])
