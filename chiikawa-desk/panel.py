"""설정 창 (파스텔 톤). 크기는 슬라이더·마우스 휠로 조절하고, 조절하는 즉시 실제 캐릭터와 창 안 미리보기에 반영된다."""
import math
from pathlib import Path

from PyQt5.QtCore import QPointF, QRectF, Qt, QTime, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTimeEdit, QVBoxLayout, QWidget,
)

from carried import make_font
from pet import CHAR_LABEL, CHARS, SCALE_MAX, SCALE_MIN

# 캐릭터 저작권 표기 (설정 창 맨 아래에만 표시, 영문)
COPYRIGHT_NOTICE = "© nagano / chiikawa committee"

DAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
CARRY_CHOICES = [("memo", "포스트잇"), ("clock", "퇴근 타이머"), ("none", "없음")]
DEFAULT_SCALE = 0.5
SLIDER_MAX = 1000
WHEEL_STEP = 45                      # 휠 한 칸 ≈ 크기 18% 변화(로그 눈금)

PASTEL_QSS = """
QDialog{background:#FFF7FA;}
QWidget#content{background:#FFF7FA;}
QScrollArea{border:none;background:transparent;}
QScrollBar:vertical{background:transparent;width:10px;margin:2px;}
QScrollBar::handle:vertical{background:#E3D3F0;border-radius:5px;min-height:30px;}
QScrollBar::handle:vertical:hover{background:#D3BFE8;}
QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
QLabel{color:#5E4B70;background:transparent;}
QLabel#hint{color:#A58FB8;font-size:11px;}
QLabel#value{color:#8B6FAE;font-weight:bold;}
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
QSlider::groove:horizontal{height:6px;background:#EEDDF2;border-radius:3px;}
QSlider::sub-page:horizontal{background:#D3C2F5;border-radius:3px;}
QSlider::handle:horizontal{width:18px;height:18px;margin:-6px 0;border-radius:9px;background:#BDA9F0;border:2px solid #FFFFFF;}
QSlider::handle:horizontal:hover{background:#A992EA;}
QPushButton{background:#F6E8F4;border:none;border-radius:12px;padding:7px 20px;color:#7B5E8E;}
QPushButton:hover{background:#F0DAEE;}
QPushButton:default{background:#BDA9F0;color:white;font-weight:bold;}
QPushButton:default:hover{background:#AB95EA;}
QPushButton#small{padding:4px 12px;border-radius:10px;}
"""
UI_DIR = (Path(__file__).resolve().parent / "ui").as_posix()
PASTEL_QSS = PASTEL_QSS.replace("@UI@", UI_DIR)


def scale_to_pos(s):
    s = min(SCALE_MAX, max(SCALE_MIN, float(s)))
    return int(round(SLIDER_MAX * math.log(s / SCALE_MIN) / math.log(SCALE_MAX / SCALE_MIN)))


def pos_to_scale(v):
    return SCALE_MIN * (SCALE_MAX / SCALE_MIN) ** (v / SLIDER_MAX)


def normalize_carry(carry, enabled):
    """퇴근 타이머는 한 마리만 들 수 있다. 겹치면 앞쪽 캐릭터만 들고 나머지는 '없음'."""
    out, used = {}, set()
    for ch in CHARS:
        kind = carry.get(ch, "memo") if ch in enabled else "none"
        if kind == "timer":                                  # 예전 '집중 타이머' 설정은 퇴근 타이머로
            kind = "clock"
        if kind == "clock":
            if kind in used:
                kind = "none"
            else:
                used.add(kind)
        out[ch] = kind if kind in dict(CARRY_CHOICES) else "memo"
    return out


class SizePreview(QWidget):
    """선택한 크기로 캐릭터들이 나란히 선 모습을 바로 보여 준다. 위에서 휠을 돌리면 크기가 바뀐다."""
    wheel = pyqtSignal(int, float)           # (휠 칸 수, 마우스의 가로 위치 0~1)

    def __init__(self, bank, chars_fn, scales_fn, parent=None):
        super().__init__(parent)
        self.bank, self.chars_fn, self.scales_fn = bank, chars_fn, scales_fn
        self.setMinimumHeight(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip("여기서 마우스 휠을 돌려도 크기가 바뀌어요")

    def wheelEvent(self, e):
        steps = int(round(e.angleDelta().y() / 120.0))
        if steps:
            self.wheel.emit(steps, e.pos().x() / max(1, self.width()))
        e.accept()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(QPen(QColor("#EBDDF3"), 1))
        p.setBrush(QColor("#FFF3F8"))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)
        chars = [c for c in self.chars_fn() if f"{c}_base" in self.bank.names]
        if not chars:
            return
        scales = self.scales_fn()
        sizes = []
        for ch in chars:
            raw = self.bank.raw(f"{ch}_base")
            s = scales.get(ch, DEFAULT_SCALE)
            sizes.append((ch, raw.width() * s, raw.height() * s))
        steps = [w * 0.8 for _, w, _ in sizes]
        total = sum(steps[:-1]) + sizes[-1][1]
        maxh = max(h for _, _, h in sizes)
        avail_w, avail_h = self.width() - 28, self.height() - 44
        fit = min(1.0, avail_w / max(1.0, total), avail_h / max(1.0, maxh))
        x = (self.width() - total * fit) / 2
        base_y = self.height() - 26
        p.setPen(QPen(QColor("#E6D3EE"), 2))
        p.drawLine(QPointF(14, base_y), QPointF(self.width() - 14, base_y))
        for (ch, w, h), step in zip(sizes, steps):
            pm = self.bank.raw(f"{ch}_base")
            p.drawPixmap(QRectF(x, base_y - h * fit, w * fit, h * fit), pm, QRectF(pm.rect()))
            x += step * fit
        p.setPen(QColor("#A58FB8"))
        p.setFont(make_font(8.5))
        note = "실제 크기 그대로" if fit >= 0.999 else f"화면에 맞춰 {int(fit * 100)}%로 줄여서 보여줘요"
        p.drawText(QRectF(0, self.height() - 22, self.width(), 18), Qt.AlignCenter, note)


class SettingsDialog(QDialog):
    def __init__(self, cfg, parent=None, bank=None, scales=None, on_live=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet(PASTEL_QSS)
        self.setFont(make_font(9.5))
        self.on_live = on_live
        self.bank = bank
        self._syncing = False
        init_scales = {ch: float((scales or {}).get(ch) or cfg["pets"].get(ch, {}).get("scale") or DEFAULT_SCALE) for ch in CHARS}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("content")
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        lay = QVBoxLayout(content)
        lay.setContentsMargins(4, 2, 8, 6)
        lay.setSpacing(6)

        # 크기 (슬라이더·휠 + 바로 미리보기)
        g = QGroupBox("캐릭터 크기 — 스크롤로 조절하면 바로 보여요")
        v = QVBoxLayout(g)
        self.preview = None
        if bank is not None:
            self.preview = SizePreview(bank, self._enabled_chars, self.current_scales)
            self.preview.wheel.connect(self._preview_wheel)
            v.addWidget(self.preview)
        self.link = QCheckBox("모두 같은 크기로 조절")
        vals = [init_scales[c] for c in CHARS if c in cfg["enabled"]] or [DEFAULT_SCALE]
        self.link.setChecked(max(vals) - min(vals) < 1e-3)
        v.addWidget(self.link)
        self.sliders, self.value_labels = {}, {}
        for ch in CHARS:
            row = QHBoxLayout()
            name = QLabel(CHAR_LABEL[ch])
            name.setMinimumWidth(56)
            sl = QSlider(Qt.Horizontal)
            sl.setRange(0, SLIDER_MAX)
            sl.setSingleStep(15)
            sl.setPageStep(120)
            sl.setValue(scale_to_pos(init_scales[ch]))
            lbl = QLabel()
            lbl.setObjectName("value")
            lbl.setMinimumWidth(92)
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.sliders[ch], self.value_labels[ch] = sl, lbl
            sl.valueChanged.connect(lambda _v, c=ch: self._slider_changed(c))
            row.addWidget(name)
            row.addWidget(sl, 1)
            row.addWidget(lbl)
            v.addLayout(row)
        row = QHBoxLayout()
        reset = QPushButton("기본 크기로")
        reset.setObjectName("small")
        reset.setAutoDefault(False)
        reset.setDefault(False)
        reset.clicked.connect(self._reset_scales)
        tip = QLabel("슬라이더나 마우스 휠로 0.08배(아주 작게)~3배까지")
        tip.setObjectName("hint")
        row.addWidget(tip, 1)
        row.addWidget(reset)
        v.addLayout(row)
        lay.addWidget(g)
        self._live_timer = QTimer(self)
        self._live_timer.setSingleShot(True)
        self._live_timer.setInterval(25)
        self._live_timer.timeout.connect(self._emit_live)
        for ch in CHARS:
            self._update_label(ch)

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
        hint = QLabel("퇴근 타이머는 한 캐릭터만 들 수 있어요. 겹치면 앞 캐릭터만 듭니다.")
        hint.setObjectName("hint")
        v.addWidget(hint)
        self.on_top = QCheckBox("항상 다른 창 위에 표시")
        self.on_top.setChecked(bool(cfg["on_top"]))
        v.addWidget(self.on_top)
        self.autostart = QCheckBox("PC를 켤 때 자동으로 실행 (Windows)")
        self.autostart.setChecked(bool(cfg.get("autostart", True)))
        v.addWidget(self.autostart)
        lay.addWidget(g)
        if self.preview is not None:
            for cb in self.show_cb.values():
                cb.toggled.connect(lambda _c: self.preview.update())

        # 함께 일하기
        g = QGroupBox("함께 일하기")
        v = QVBoxLayout(g)
        fo = cfg["follow"]
        self.follow_on = QCheckBox("내가 컴퓨터를 쓸 때만 키보드를 치기")
        self.follow_on.setChecked(bool(fo["enabled"]))
        self.follow_sec = QSpinBox()
        self.follow_sec.setRange(2, 600)
        self.follow_sec.setValue(int(fo["idle_seconds"]))
        self.follow_sec.setSuffix(" 초")
        row = QHBoxLayout()
        row.addWidget(QLabel("입력이 없으면 쉬기까지"))
        row.addWidget(self.follow_sec)
        row.addStretch(1)
        self.away_min = QSpinBox()
        self.away_min.setRange(1, 600)
        self.away_min.setValue(int(fo.get("away_minutes", 30)))
        self.away_min.setSuffix(" 분")
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("오래 쉬면 차 마시기까지"))
        row2.addWidget(self.away_min)
        row2.addStretch(1)
        note = QLabel("마지막 입력이 몇 초 전인지 시간만 확인합니다. 무엇을 입력했는지는 읽지 않아요.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        v.addWidget(self.follow_on)
        v.addLayout(row)
        v.addLayout(row2)
        v.addWidget(note)
        lay.addWidget(g)

        # 퇴근
        g = QGroupBox("퇴근 타이머")
        v = QVBoxLayout(g)
        co = cfg["clockout"]
        self.co_on = QCheckBox("퇴근 타이머 사용")
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
        self.co_warn = QCheckBox("퇴근 30분·10분 전에 머리 위 물건이 색으로 알려 주기")
        self.co_warn.setChecked(bool(co["warn"]))
        v.addWidget(self.co_on)
        v.addLayout(row)
        v.addLayout(days)
        v.addWidget(self.co_warn)
        lay.addWidget(g)
        lay.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("확인")
        bb.button(QDialogButtonBox.Ok).setDefault(True)
        bb.button(QDialogButtonBox.Cancel).setText("취소")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        outer.addWidget(bb)
        credit = QLabel(COPYRIGHT_NOTICE)                             # 설정 창 맨 아래 저작권 표기
        credit.setObjectName("hint")
        credit.setAlignment(Qt.AlignCenter)
        outer.addWidget(credit)

        scr = QApplication.primaryScreen().availableGeometry()
        self.resize(540, max(420, min(900, int(scr.height() * 0.88))))

    # -- 크기 ---------------------------------------------------------------
    def _enabled_chars(self):
        return [c for c in CHARS if self.show_cb[c].isChecked()]

    def current_scales(self):
        return {ch: pos_to_scale(sl.value()) for ch, sl in self.sliders.items()}

    def _update_label(self, ch):
        s = pos_to_scale(self.sliders[ch].value())
        self.value_labels[ch].setText(f"{s:.2f}배 ({round(s * 100)}%)")

    def _slider_changed(self, ch):
        if self._syncing:
            return
        if self.link.isChecked():                                   # 하나를 움직이면 모두 같이
            self._syncing = True
            val = self.sliders[ch].value()
            for c, sl in self.sliders.items():
                if c != ch:
                    sl.setValue(val)
            self._syncing = False
        for c in CHARS:
            self._update_label(c)
        if self.preview is not None:
            self.preview.update()
        self._live_timer.start()                                    # 실제 캐릭터에 바로 반영(살짝 모아서)

    def _emit_live(self):
        if self.on_live is not None:
            self.on_live(self.current_scales())

    def _reset_scales(self):
        self._syncing = True
        for sl in self.sliders.values():
            sl.setValue(scale_to_pos(DEFAULT_SCALE))
        self._syncing = False
        for c in CHARS:
            self._update_label(c)
        if self.preview is not None:
            self.preview.update()
        self._live_timer.start()

    def _preview_wheel(self, steps, xfrac):
        chars = self._enabled_chars()
        if self.link.isChecked() or not chars:
            target = self.sliders[chars[0] if chars else CHARS[0]]
        else:
            target = self.sliders[chars[min(len(chars) - 1, int(xfrac * len(chars)))]]
        target.setValue(max(0, min(SLIDER_MAX, target.value() + steps * WHEEL_STEP)))

    # -- 값 -----------------------------------------------------------------
    def values(self):
        enabled = [ch for ch in CHARS if self.show_cb[ch].isChecked()] or [CHARS[0]]
        carry = normalize_carry({ch: self.carry_cb[ch].currentData() for ch in CHARS}, enabled)
        return {
            "follow": {"enabled": self.follow_on.isChecked(), "idle_seconds": self.follow_sec.value(), "away_minutes": self.away_min.value()},
            "enabled": enabled, "on_top": self.on_top.isChecked(), "autostart": self.autostart.isChecked(), "carry": carry,
            "scales": self.current_scales(),
            "clockout": {
                "enabled": self.co_on.isChecked(), "time": self.co_time.time().toString("HH:mm"),
                "days": [i for i, cb in enumerate(self.co_days) if cb.isChecked()],
                "warn": [30, 10] if self.co_warn.isChecked() else [],
            },
        }
