"""머리 위에 올리는 타이머 · 퇴근 시계. (포스트잇과 같은 방식으로 접고 펼친다)"""
from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QPushButton

from carried import HEADER_H, CarriedItem, make_font

BTN_QSS = """
QPushButton{background:rgba(255,255,255,175);border:1px solid rgba(0,0,0,40);border-radius:8px;
            padding:2px 2px;color:#3a3a3a;font-size:11px;}
QPushButton:hover{background:rgba(255,255,255,240);}
QPushButton#primary{background:#6C7BF0;color:white;border:none;font-weight:bold;}
QPushButton#primary:hover{background:#5968de;}
"""
TIMER_COLORS = {"idle": "#D9DEF7", "focus": "#C4D0FB", "rest": "#CDEBD8", "paused": "#E3E5EC", "done": "#F9C9D6"}


class TimerItem(CarriedItem):
    primary_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()
    cheer_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    OPEN_W, OPEN_H = 270, 152

    def __init__(self, on_top=True):
        super().__init__(on_top)
        self.kind, self.phase_text, self.time_text = "idle", "대기", "25:00"
        self.leave_text, self.leave_color = "", "#7b7562"
        self.setStyleSheet(BTN_QSS)
        self.primary = QPushButton("시작", self)
        self.primary.setObjectName("primary")
        self.b_reset, self.b_cheer, self.b_set = QPushButton("초기화", self), QPushButton("응원", self), QPushButton("⚙", self)
        self.primary.clicked.connect(self.primary_clicked)
        self.b_reset.clicked.connect(self.reset_clicked)
        self.b_cheer.clicked.connect(self.cheer_clicked)
        self.b_set.clicked.connect(self.settings_clicked)
        for b in (self.primary, self.b_reset, self.b_cheer, self.b_set):
            b.hide()
        self.apply_layout()

    def refresh(self, kind, phase_text, time_text, primary_text, leave_text="", leave_color="#7b7562"):
        changed = (kind, phase_text, time_text, leave_text) != (self.kind, self.phase_text, self.time_text, self.leave_text)
        self.kind, self.phase_text, self.time_text = kind, phase_text, time_text
        self.leave_text, self.leave_color = leave_text, leave_color
        if self.primary.text() != primary_text:
            self.primary.setText(primary_text)
        if changed:
            self.update()

    def accent(self):
        return QColor(TIMER_COLORS.get(self.kind, TIMER_COLORS["idle"]))

    def on_layout(self, r):
        show = self.is_open()
        y = r.bottom() - 36
        x = r.x() + 10
        w = r.width() - 20
        pw = int(w * 0.36)
        self.primary.setGeometry(int(x), int(y), pw, 26)
        rest = (w - pw - 3 * 4) / 3.0
        self.b_reset.setGeometry(int(x + pw + 4), int(y), int(rest), 26)
        self.b_cheer.setGeometry(int(x + pw + 8 + rest), int(y), int(rest), 26)
        self.b_set.setGeometry(int(x + pw + 12 + 2 * rest), int(y), int(rest), 26)
        for b in (self.primary, self.b_reset, self.b_cheer, self.b_set):
            b.setVisible(show)

    def paint_open(self, p, r, base):
        p.setPen(QColor("#4b4b57"))
        p.setFont(make_font(8.5, True))
        p.drawText(QRectF(r.x() + 12, r.y() + 4, 110, 20), Qt.AlignLeft | Qt.AlignVCenter, "집중 타이머 · " + self.phase_text)
        p.setPen(QColor("#33333d"))
        p.setFont(make_font(24, True))
        p.drawText(QRectF(r.x(), r.y() + HEADER_H + 2, r.width(), 46), Qt.AlignCenter, self.time_text)
        p.setPen(QColor(self.leave_color))
        p.setFont(make_font(8))
        p.drawText(QRectF(r.x(), r.y() + HEADER_H + 46, r.width(), 18), Qt.AlignCenter, self.leave_text)

    def paint_mini(self, p, r, base):
        s = self.mscale
        p.setPen(QColor("#5b5b6a"))
        p.setFont(make_font(max(5.5, 7 * s), True))
        p.drawText(QRectF(r.x(), r.y() + 3 * s, r.width(), 14 * s), Qt.AlignCenter, self.phase_text)
        p.setPen(QColor("#33333d"))
        p.setFont(make_font(max(7, 11 * s), True))
        p.drawText(QRectF(r.x(), r.y() + 15 * s, r.width(), 26 * s), Qt.AlignCenter, self.time_text)

    def build_menu(self, m):
        m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)
        m.addAction("설정").triggered.connect(self.settings_clicked)


CLOCK_COLORS = {"far": "#E4E6EE", "warn30": "#FAD7B0", "warn10": "#F6C2C2", "now": "#F4AFAF", "over": "#E4E6EE", "off": "#ECECF0"}


class ClockItem(CarriedItem):
    skip_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    OPEN_W, OPEN_H = 184, 124

    def __init__(self, on_top=True):
        super().__init__(on_top)
        self.phase, self.big, self.sub, self.clock_time = "off", "--", "퇴근 시간 꺼짐", "18:00"
        self.setStyleSheet(BTN_QSS)
        self.b_skip, self.b_set = QPushButton("오늘은 끄기", self), QPushButton("설정", self)
        self.b_skip.clicked.connect(self.skip_clicked)
        self.b_set.clicked.connect(self.settings_clicked)
        self.b_skip.hide()
        self.b_set.hide()
        self.apply_layout()

    def refresh(self, phase, big, sub, clock_time):
        if (phase, big, sub, clock_time) != (self.phase, self.big, self.sub, self.clock_time):
            self.phase, self.big, self.sub, self.clock_time = phase, big, sub, clock_time
            self.update()

    def accent(self):
        return QColor(CLOCK_COLORS.get(self.phase, CLOCK_COLORS["far"]))

    def on_layout(self, r):
        show = self.is_open()
        y = r.bottom() - 34
        self.b_skip.setGeometry(int(r.x() + 10), int(y), int(r.width() * 0.56), 26)
        self.b_set.setGeometry(int(r.x() + 16 + r.width() * 0.56), int(y), int(r.width() * 0.44 - 26), 26)
        self.b_skip.setVisible(show)
        self.b_set.setVisible(show)

    def _big_color(self):
        return {"warn30": "#D98324", "warn10": "#E5484D", "now": "#E5484D"}.get(self.phase, "#33333d")

    def paint_open(self, p, r, base):
        p.setPen(QColor("#4b4b57"))
        p.setFont(make_font(8.5, True))
        p.drawText(QRectF(r.x() + 12, r.y() + 4, 120, 20), Qt.AlignLeft | Qt.AlignVCenter, f"퇴근 시계 · {self.clock_time}")
        p.setPen(QColor(self._big_color()))
        p.setFont(make_font(22, True))
        p.drawText(QRectF(r.x(), r.y() + HEADER_H, r.width(), 40), Qt.AlignCenter, self.big)
        p.setPen(QColor("#6b6b78"))
        p.setFont(make_font(8))
        p.drawText(QRectF(r.x(), r.y() + HEADER_H + 38, r.width(), 18), Qt.AlignCenter, self.sub)

    def paint_mini(self, p, r, base):
        s = self.mscale
        p.setPen(QColor("#5b5b6a"))
        p.setFont(make_font(max(5.5, 7.5 * s), True))
        p.drawText(QRectF(r.x(), r.y() + 3 * s, r.width(), 14 * s), Qt.AlignCenter, "퇴근")
        p.setPen(QColor(self._big_color()))
        p.setFont(make_font(max(6.5, 10.5 * s), True))
        p.drawText(QRectF(r.x(), r.y() + 15 * s, r.width(), 26 * s), Qt.AlignCenter, self.big)

    def build_menu(self, m):
        m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)
        m.addAction("오늘은 퇴근 알림 끄기").triggered.connect(self.skip_clicked)
        m.addAction("설정").triggered.connect(self.settings_clicked)
