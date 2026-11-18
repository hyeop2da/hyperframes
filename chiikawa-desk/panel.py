"""타이머 조작 카드 · 남은 시간 칩 · 설정 창. (말풍선은 쓰지 않는다)"""
from PyQt5.QtCore import QPoint, QRectF, Qt, QTime, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QPushButton, QSpinBox, QTimeEdit, QVBoxLayout, QWidget,
)

from pet import CHAR_LABEL, CHARS
from postit import make_font

DAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
CARD_QSS = """
QLabel{color:#3a3a3a;background:transparent;}
QPushButton{background:rgba(255,255,255,170);border:1px solid rgba(0,0,0,40);border-radius:9px;
            padding:5px 6px;color:#3a3a3a;}
QPushButton:hover{background:rgba(255,255,255,235);}
QPushButton#primary{background:#6C7BF0;color:white;border:none;font-weight:bold;}
QPushButton#primary:hover{background:#5968de;}
QPushButton#close{border:none;background:transparent;padding:0;color:#8a8578;font-size:14px;}
"""


def _fix_screen(widget, anchor_rect_top, center_x):
    """위젯 하나를 (center_x, 아래=anchor_rect_top) 에 두되 화면 밖으로 나가지 않게 한다."""
    scr = QApplication.screenAt(QPoint(int(center_x), int(anchor_rect_top))) or QApplication.primaryScreen()
    a = scr.availableGeometry()
    x = int(center_x - widget.width() / 2)
    y = int(anchor_rect_top - widget.height())
    x = max(a.left() + 2, min(x, a.right() - widget.width() - 2))
    y = max(a.top() + 2, y)
    widget.move(x, y)


class TimerCard(QWidget):
    primary_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()
    cheer_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()

    def __init__(self, on_top=True):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.setStyleSheet(CARD_QSS)
        self.setFixedSize(278, 140)

        self.phase = QLabel("대기")
        self.phase.setFont(make_font(9, True))
        close = QPushButton("✕")
        close.setObjectName("close")
        close.setFixedSize(20, 20)
        close.clicked.connect(self.hide)
        top = QHBoxLayout()
        top.addWidget(self.phase)
        top.addStretch(1)
        top.addWidget(close)

        self.time = QLabel("25:00")
        self.time.setFont(make_font(26, True))
        self.time.setAlignment(Qt.AlignCenter)
        self.leave = QLabel("")
        self.leave.setFont(make_font(8))
        self.leave.setAlignment(Qt.AlignCenter)

        self.primary = QPushButton("시작")
        self.primary.setObjectName("primary")
        self.primary.clicked.connect(self.primary_clicked)
        b_reset, b_cheer, b_set = QPushButton("초기화"), QPushButton("응원"), QPushButton("⚙")
        b_set.setFixedWidth(34)
        self.primary.setMinimumWidth(84)
        b_reset.clicked.connect(self.reset_clicked)
        b_cheer.clicked.connect(self.cheer_clicked)
        b_set.clicked.connect(self.settings_clicked)
        row = QHBoxLayout()
        for b in (self.primary, b_reset, b_cheer, b_set):
            row.addWidget(b)
        row.setSpacing(5)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(2)
        lay.addLayout(top)
        lay.addWidget(self.time)
        lay.addWidget(self.leave)
        lay.addLayout(row)

    def refresh(self, phase_text, time_text, primary_text, leave_text="", leave_color="#7b7562"):
        self.phase.setText(phase_text)
        self.time.setText(time_text)
        self.primary.setText(primary_text)
        self.leave.setText(leave_text)
        self.leave.setStyleSheet(f"color:{leave_color};")

    def place_above(self, top_y, center_x):
        _fix_screen(self, top_y - 6, center_x)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(0, 0, 0, 38), 1))
        p.setBrush(QColor(255, 251, 246, 240))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 16, 16)


class Chip(QWidget):
    """머리 위 쪽지 바로 위에 뜨는 작은 알약 — 남은 시간만 보여준다."""

    def __init__(self, on_top=True):
        flags = Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        if hasattr(Qt, "WindowTransparentForInput"):
            flags |= Qt.WindowTransparentForInput
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self._text, self._color = "", QColor("#6C7BF0")
        self._font = make_font(8.5, True)

    def set_content(self, text, color="#6C7BF0"):
        if text != self._text or color != self._color.name():
            self._text, self._color = text, QColor(color)
            w = QFontMetrics(self._font).horizontalAdvance(text) + 22
            self.setFixedSize(max(44, w), 22)
            self.update()

    def place_above(self, top_y, center_x):
        _fix_screen(self, top_y - 3, center_x)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 11, 11)
        p.setPen(QColor("white"))
        p.setFont(self._font)
        p.drawText(self.rect(), Qt.AlignCenter, self._text)


class SettingsDialog(QDialog):
    def __init__(self, cfg, probe, reactor, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.probe, self.reactor = probe, reactor
        lay = QVBoxLayout(self)

        # 타이머
        g = QGroupBox("집중 타이머")
        f = QFormLayout(g)
        self.focus_min = QSpinBox()
        self.focus_min.setRange(1, 180)
        self.focus_min.setValue(int(cfg["focus_min"]))
        self.focus_min.setSuffix(" 분")
        self.rest_min = QSpinBox()
        self.rest_min.setRange(1, 60)
        self.rest_min.setValue(int(cfg["rest_min"]))
        self.rest_min.setSuffix(" 분")
        f.addRow("집중 시간", self.focus_min)
        f.addRow("휴식 시간", self.rest_min)
        lay.addWidget(g)

        # 퇴근
        g = QGroupBox("퇴근 시간")
        v = QVBoxLayout(g)
        co = cfg["clockout"]
        self.co_on = QCheckBox("퇴근 시간 표시 사용")
        self.co_on.setChecked(bool(co["enabled"]))
        self.co_time = QTimeEdit(QTime.fromString(co["time"], "HH:mm"))
        self.co_time.setDisplayFormat("HH:mm")
        row = QHBoxLayout()
        row.addWidget(QLabel("퇴근 시각"))
        row.addWidget(self.co_time)
        row.addStretch(1)
        self.co_days = []
        days = QHBoxLayout()
        for i, name in enumerate(DAY_LABELS):
            cb = QCheckBox(name)
            cb.setChecked(i in co["days"])
            self.co_days.append(cb)
            days.addWidget(cb)
        self.co_warn = QCheckBox("퇴근 30분·10분 전에 쪽지가 알려 주기")
        self.co_warn.setChecked(bool(co["warn"]))
        for item in (self.co_on, row, days, self.co_warn):
            v.addLayout(item) if hasattr(item, "addWidget") else v.addWidget(item)
        lay.addWidget(g)

        # 작업 반응
        g = QGroupBox("내 작업에 반응하기")
        v = QVBoxLayout(g)
        self.react = QCheckBox("다른 프로그램에서 작업할 때도 캐릭터가 함께 움직이기")
        self.react.setChecked(bool(cfg["react"]))
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.live = QLabel()
        v.addWidget(self.react)
        v.addWidget(self.status)
        v.addWidget(self.live)
        lay.addWidget(g)
        if probe.available:
            self.status.setText(f"감지 방식: {probe.name}\n(입력한 글자·키 종류·프로그램 이름은 읽지도 저장하지도 않습니다)")
        else:
            self.status.setText(f"⚠ 이 환경에서는 지원되지 않습니다: {probe.reason}\n(타이머와 캐릭터·포스트잇 기능은 그대로 동작합니다)")
            self.react.setEnabled(False)
        self._live_timer = QTimer(self)
        self._live_timer.timeout.connect(self._tick)
        self._live_timer.start(500)
        self._tick()

        # 캐릭터
        g = QGroupBox("캐릭터")
        v = QVBoxLayout(g)
        self.show_cb = {}
        row = QHBoxLayout()
        for ch in CHARS:
            cb = QCheckBox(CHAR_LABEL[ch])
            cb.setChecked(ch in cfg["enabled"])
            self.show_cb[ch] = cb
            row.addWidget(cb)
        v.addLayout(row)
        self.leader = QComboBox()
        for ch in CHARS:
            self.leader.addItem(CHAR_LABEL[ch], ch)
        self.leader.setCurrentIndex(max(0, CHARS.index(cfg["leader"]) if cfg["leader"] in CHARS else 0))
        row = QHBoxLayout()
        row.addWidget(QLabel("대표 캐릭터 (타이머 카드·남은 시간 표시)"))
        row.addWidget(self.leader)
        v.addLayout(row)
        self.on_top = QCheckBox("항상 다른 창 위에 표시")
        self.on_top.setChecked(bool(cfg["on_top"]))
        v.addWidget(self.on_top)
        lay.addWidget(g)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확인")
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _tick(self):
        if self.probe.available:
            ms = self.probe.idle_ms()
            self.live.setText("마지막 입력 후: " + ("-" if ms is None else f"{ms / 1000:.1f}초") +
                              f"   (현재 상태: {self.reactor.state})")

    def values(self):
        enabled = [ch for ch in CHARS if self.show_cb[ch].isChecked()] or [CHARS[0]]
        leader = self.leader.currentData()
        if leader not in enabled:
            leader = enabled[0]
        return {
            "focus_min": self.focus_min.value(), "rest_min": self.rest_min.value(),
            "react": self.react.isChecked(), "enabled": enabled, "leader": leader, "on_top": self.on_top.isChecked(),
            "clockout": {
                "enabled": self.co_on.isChecked(), "time": self.co_time.time().toString("HH:mm"),
                "days": [i for i, cb in enumerate(self.co_days) if cb.isChecked()],
                "warn": [30, 10] if self.co_warn.isChecked() else [],
            },
        }
