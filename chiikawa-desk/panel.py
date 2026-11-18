"""설정 창 (파스텔 톤). 타이머·퇴근 시계는 머리 위 물건이고, 말풍선은 쓰지 않는다."""
from pathlib import Path

from PyQt5.QtCore import Qt, QTime
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QSpinBox, QTimeEdit, QVBoxLayout,
)

from carried import make_font
from pet import CHAR_LABEL, CHARS

DAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
CARRY_CHOICES = [("memo", "포스트잇"), ("timer", "집중 타이머"), ("clock", "퇴근 시계"), ("none", "없음")]

PASTEL_QSS = """
QDialog{background:#FFF7FA;}
QLabel{color:#5E4B70;background:transparent;}
QLabel#hint{color:#A58FB8;font-size:11px;}
QGroupBox{background:#FFFDFE;border:1px solid #F1DCEA;border-radius:16px;margin-top:16px;padding:14px 12px 10px 12px;
          color:#8B6FAE;font-weight:bold;}
QGroupBox::title{subcontrol-origin:margin;subcontrol-position:top left;left:14px;padding:0 8px;background:#FFF7FA;
                 color:#8B6FAE;border-radius:8px;}
QCheckBox{color:#5E4B70;spacing:8px;background:transparent;}
QCheckBox::indicator{width:16px;height:16px;border-radius:5px;border:1px solid #D9C6E8;background:#FFFFFF;}
QCheckBox::indicator:checked{background:#BDA9F0;border:1px solid #A58FE6;}
QCheckBox::indicator:hover{border:1px solid #BDA9F0;}
QSpinBox,QTimeEdit,QComboBox{background:#FFFFFF;border:1px solid #E6D6F0;border-radius:9px;padding:4px 8px;color:#5E4B70;
                             selection-background-color:#E3D7FA;selection-color:#4A3A60;min-height:20px;}
QSpinBox:focus,QTimeEdit:focus,QComboBox:focus{border:1px solid #BDA9F0;}
QComboBox::drop-down{border:none;width:26px;}
QComboBox::down-arrow{image:url(@UI@/arrow_down.png);width:10px;height:6px;margin-right:8px;}
QSpinBox::up-button,QTimeEdit::up-button{subcontrol-origin:border;subcontrol-position:top right;width:22px;border:none;
                                         background:#F6E8F4;border-top-right-radius:8px;}
QSpinBox::down-button,QTimeEdit::down-button{subcontrol-origin:border;subcontrol-position:bottom right;width:22px;border:none;
                                             background:#F6E8F4;border-bottom-right-radius:8px;}
QSpinBox::up-button:hover,QTimeEdit::up-button:hover,QSpinBox::down-button:hover,QTimeEdit::down-button:hover{background:#EFD9EC;}
QSpinBox::up-arrow,QTimeEdit::up-arrow{image:url(@UI@/arrow_up.png);width:10px;height:6px;}
QSpinBox::down-arrow,QTimeEdit::down-arrow{image:url(@UI@/arrow_down.png);width:10px;height:6px;}
QComboBox QAbstractItemView{background:#FFFFFF;border:1px solid #E6D6F0;selection-background-color:#EFE6FC;
                            selection-color:#4A3A60;outline:0;}
QPushButton{background:#F6E8F4;border:none;border-radius:12px;padding:7px 20px;color:#7B5E8E;}
QPushButton:hover{background:#F0DAEE;}
QPushButton:default{background:#BDA9F0;color:white;font-weight:bold;}
QPushButton:default:hover{background:#AB95EA;}
"""


UI_DIR = (Path(__file__).resolve().parent / "ui").as_posix()
PASTEL_QSS = PASTEL_QSS.replace("@UI@", UI_DIR)


def normalize_carry(carry, enabled):
    """타이머·퇴근 시계는 한 마리만 들 수 있다. 겹치면 앞쪽 캐릭터만 들고 나머지는 '없음'."""
    out, used = {}, set()
    for ch in CHARS:
        kind = carry.get(ch, "memo") if ch in enabled else "none"
        if kind in ("timer", "clock"):
            if kind in used:
                kind = "none"
            else:
                used.add(kind)
        out[ch] = kind if kind in dict(CARRY_CHOICES) else "memo"
    return out


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet(PASTEL_QSS)
        self.setFont(make_font(9.5))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(6)

        # 캐릭터 · 머리 위에 올릴 것
        g = QGroupBox("캐릭터와 머리 위에 올릴 것")
        v = QVBoxLayout(g)
        self.show_cb, self.carry_cb = {}, {}
        for ch in CHARS:
            row = QHBoxLayout()
            cb = QCheckBox(CHAR_LABEL[ch])
            cb.setChecked(ch in cfg["enabled"])
            combo = QComboBox()
            for key, label in CARRY_CHOICES:
                combo.addItem(label, key)
            combo.setCurrentIndex(max(0, [k for k, _ in CARRY_CHOICES].index(cfg["carry"].get(ch, "memo"))))
            self.show_cb[ch], self.carry_cb[ch] = cb, combo
            row.addWidget(cb, 1)
            row.addWidget(QLabel("머리 위:"))
            row.addWidget(combo, 1)
            v.addLayout(row)
        hint = QLabel("집중 타이머와 퇴근 시계는 한 캐릭터만 들 수 있어요. 겹치면 앞 캐릭터만 듭니다.")
        hint.setObjectName("hint")
        v.addWidget(hint)
        self.on_top = QCheckBox("항상 다른 창 위에 표시")
        self.on_top.setChecked(bool(cfg["on_top"]))
        v.addWidget(self.on_top)
        lay.addWidget(g)

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
        self.co_warn = QCheckBox("퇴근 30분·10분 전에 머리 위 물건이 알려 주기")
        self.co_warn.setChecked(bool(co["warn"]))
        v.addWidget(self.co_on)
        v.addLayout(row)
        v.addLayout(days)
        v.addWidget(self.co_warn)
        lay.addWidget(g)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확인")
        bb.button(QDialogButtonBox.Ok).setDefault(True)
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        enabled = [ch for ch in CHARS if self.show_cb[ch].isChecked()] or [CHARS[0]]
        carry = normalize_carry({ch: self.carry_cb[ch].currentData() for ch in CHARS}, enabled)
        return {
            "focus_min": self.focus_min.value(), "rest_min": self.rest_min.value(),
            "enabled": enabled, "on_top": self.on_top.isChecked(), "carry": carry,
            "clockout": {
                "enabled": self.co_on.isChecked(), "time": self.co_time.time().toString("HH:mm"),
                "days": [i for i, cb in enumerate(self.co_days) if cb.isChecked()],
                "warn": [30, 10] if self.co_warn.isChecked() else [],
            },
        }
