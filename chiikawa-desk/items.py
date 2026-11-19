"""머리 위에 올리는 퇴근 타이머. (포스트잇과 같은 방식으로 접고 펼친다)"""
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

CLOCK_COLORS = {"far": "#E4E6EE", "warn30": "#FAD7B0", "warn10": "#F6C2C2", "now": "#F4AFAF", "over": "#E4E6EE", "off": "#ECECF0"}


class ClockItem(CarriedItem):
    skip_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    OPEN_W, OPEN_H = 190, 136

    def __init__(self, on_top=True):
        super().__init__(on_top)
        self.phase, self.big, self.sub, self.clock_time = "off", "--", "퇴근 시간 꺼짐", "18:00"
        self.setStyleSheet(BTN_QSS)
        self.b_skip, self.b_set = QPushButton("오늘은 끄기", self), QPushButton("설정", self)
        self.b_skip.clicked.connect(self.skip_clicked)
        self.b_set.clicked.connect(self.settings_clicked)
        self.b_skip.hide()
        self.b_set.hide()
        self.init_progress()
        self.apply_layout()

    def refresh(self, phase, big, sub, clock_time):
        if (phase, big, sub, clock_time) != (self.phase, self.big, self.sub, self.clock_time):
            self.phase, self.big, self.sub, self.clock_time = phase, big, sub, clock_time
            self.update()

    def accent(self):
        return QColor(CLOCK_COLORS.get(self.phase, CLOCK_COLORS["far"]))

    def on_layout(self, r, show):
        y = r.bottom() - 36
        self.b_skip.setGeometry(int(r.x() + 10), int(y), int(r.width() * 0.56), 26)
        self.b_set.setGeometry(int(r.x() + 16 + r.width() * 0.56), int(y), int(r.width() * 0.44 - 26), 26)
        self.b_skip.setVisible(show)
        self.b_set.setVisible(show)

    def _big_color(self):
        return {"warn30": "#D98324", "warn10": "#E5484D", "now": "#E5484D", "over": "#E5484D"}.get(self.phase, "#33333d")

    def paint_open(self, p, r, base):
        p.setPen(QColor("#E5484D") if self.phase in ("warn10", "now", "over") else QColor("#4b4b57"))
        p.setFont(make_font(8.5, True))
        p.drawText(QRectF(r.x() + 14, r.y() + 8, r.width() - 80, 20), Qt.AlignLeft | Qt.AlignVCenter, f"퇴근 타이머 · {self.clock_time}")
        p.setPen(QColor(self._big_color()))
        p.setFont(make_font(22, True))
        p.drawText(QRectF(r.x(), r.y() + HEADER_H - 2, r.width(), 40), Qt.AlignCenter, self.big)
        p.setPen(QColor("#E5484D") if self.phase in ("warn10", "now", "over") else QColor("#6b6b78"))
        p.setFont(make_font(8))
        p.drawText(QRectF(r.x(), r.y() + HEADER_H + 36, r.width(), 18), Qt.AlignCenter, self.sub)

    def paint_mini(self, p, r, base):
        s = self.mscale
        urgent = self.phase in ("warn10", "now", "over")
        p.setPen(QColor("#E5484D") if urgent else QColor("#5b5b6a"))              # 임박하면 글자가 모두 빨갛게
        p.setFont(make_font(max(5.5, 7.5 * s), True))
        p.drawText(QRectF(r.x(), r.y() + 3 * s, r.width(), 14 * s), Qt.AlignCenter, "퇴근")
        p.setPen(QColor(self._big_color()))
        p.setFont(make_font(max(6.5, 10.5 * s), True))
        p.drawText(QRectF(r.x(), r.y() + 15 * s, r.width(), 26 * s), Qt.AlignCenter, self.big)

    def build_menu(self, m):
        m.addAction("접기" if self.is_open() else "펼치기").triggered.connect(self.toggle)
        m.addAction("오늘은 퇴근 알림 끄기").triggered.connect(self.skip_clicked)
        m.addAction("설정").triggered.connect(self.settings_clicked)
