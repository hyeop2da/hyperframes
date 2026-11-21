"""설정 창 (파스텔 톤). 크기는 슬라이더·마우스 휠로 조절하고, 조절하는 즉시 실제 캐릭터와 창 안 미리보기에 반영된다."""
import math
from pathlib import Path

from PyQt5.QtCore import QPointF, QRectF, Qt, QTime, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen
from PyQt5.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider, QSpinBox, QTimeEdit, QVBoxLayout, QWidget,
)

from carried import make_font
from pet import ALL_CHARS, CHAR_LABEL, CHARS, PACK_IDS, PACK_LABEL, PACK_SPECIES, POCHACCO_IDS, SCALE_MAX, SCALE_MIN, species

# 캐릭터 저작권 표기 (설정 창 맨 아래에만 표시, 영문)
COPYRIGHT_NOTICE = "© nagano / chiikawa committee"
SANRIO_NOTICE = "© 1989, 2026 SANRIO CO., LTD."          # 포차코가 나올 때만 함께 보인다
PACK_CREDIT = {"pochacco": SANRIO_NOTICE, "kitty": "© 1976, 2026 SANRIO CO., LTD."}   # 캐릭터가 나올 때만 보인다

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
QSpinBox,QTimeEdit,QComboBox,QLineEdit{background:#FFFFFF;border:1px solid #E6D6F0;border-radius:9px;padding:4px 8px;color:#5E4B70;
                             selection-background-color:#E3D7FA;selection-color:#4A3A60;min-height:20px;}
QSpinBox:focus,QTimeEdit:focus,QComboBox:focus,QLineEdit:focus{border:1px solid #BDA9F0;}
QLineEdit[bad="true"]{border:1px solid #E5484D;}
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


def parse_clock_text(text):
    """키보드로 친 시각을 해석한다: '18:30' · '1830' · '930' · '18' · '18시 30분' → QTime, 잘못되면 None."""
    import re
    s = (text or "").strip().replace("：", ":")
    m = re.fullmatch(r"(\d{1,2})\s*(?:시|:|\.)\s*(\d{1,2})\s*(?:분)?", s) or re.fullmatch(r"(\d{1,2})\s*시?", s)
    if m:
        h, mi = int(m.group(1)), int(m.group(2)) if m.lastindex == 2 else 0
    else:
        d = re.fullmatch(r"(\d{3,4})", s)
        if not d:
            return None
        h, mi = int(d.group(1)[:-2]), int(d.group(1)[-2:])
    if 0 <= h < 24 and 0 <= mi < 60:
        return QTime(h, mi)
    return None


class TimeField(QLineEdit):
    """키보드로 바로 쓰는 시각 입력칸(HH:MM). 칸을 누르고 숫자만 쳐도 된다(예: 1830). 잘못 쓰면 이전 값으로 돌아간다."""

    def __init__(self, value, parent=None):
        super().__init__(parent)
        self._t = parse_clock_text(value) or QTime(18, 0)
        self.setText(self._t.toString("HH:mm"))
        self.setMaxLength(8)
        self.setFixedWidth(96)
        self.setAlignment(Qt.AlignCenter)
        self.setPlaceholderText("18:00")
        self.editingFinished.connect(self.commit)
        self.textEdited.connect(lambda _t: self.setProperty("bad", False) or self.style().polish(self))

    def commit(self):
        t = parse_clock_text(self.text())
        if t is None:
            self.setProperty("bad", True)
            self.style().polish(self)
            self.setText(self._t.toString("HH:mm"))
            return
        self._t = t
        self.setText(t.toString("HH:mm"))

    def time(self):
        self.commit()
        return self._t

    def setTime(self, t):
        self._t = t
        self.setText(t.toString("HH:mm"))


def normalize_carry(carry, enabled):
    """퇴근 타이머는 한 마리만 들 수 있다(겹치는 저장값은 앞쪽 캐릭터만 들고 나머지는 '없음'; 새로 고를 때는 고른 쪽이 갖도록 set_carry·설정 창에서 먼저 정리한다).
    화면에 없는 캐릭터의 선택은 그대로 보관한다(다시 나타나면 원래 들던 것을 든다)."""
    out, used = {}, set()
    for ch in ALL_CHARS:
        kind = carry.get(ch, "memo")
        if ch not in enabled:
            out[ch] = "none" if kind == "clock" else (kind if kind in dict(CARRY_CHOICES) else "memo")
            continue
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
        chars = [c for c in self.chars_fn() if f"{species(c)}_base" in self.bank.names]
        if not chars:
            return
        scales = self.scales_fn()
        sizes = []
        for ch in chars:
            raw = self.bank.raw(f"{species(ch)}_base")
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
            pm = self.bank.raw(f"{species(ch)}_base")
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
        init_scales = {ch: float((scales or {}).get(ch) or cfg["pets"].get(ch, {}).get("scale") or DEFAULT_SCALE) for ch in ALL_CHARS}
        self.cfg_carry = dict(cfg["carry"])
        self.pack_ready = {sp: bank is not None and bank.has_char(sp) for sp in PACK_SPECIES}   # 팩이 있는 캐릭터만 쓴다
        self.poch_ready = self.pack_ready["pochacco"]
        self.ids = [c for c in ALL_CHARS if c in CHARS or self.pack_ready.get(species(c), False)]

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
        vals = [init_scales[c] for c in self.ids if c in cfg["enabled"]] or [DEFAULT_SCALE]
        self.link.setChecked(max(vals) - min(vals) < 1e-3)
        v.addWidget(self.link)
        self.sliders, self.value_labels, self.slider_rows = {}, {}, {}
        for ch in self.ids:
            rowbox = QWidget()
            row = QHBoxLayout(rowbox)
            row.setContentsMargins(0, 0, 0, 0)
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
            self.slider_rows[ch] = rowbox
            v.addWidget(rowbox)
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
        for ch in self.ids:
            self._update_label(ch)

        # 캐릭터 · 머리 위에 올릴 것
        g = QGroupBox("나타날 캐릭터와 머리 위에 올릴 것")
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
            combo.currentIndexChanged.connect(lambda _i, c=ch: self._carry_changed(c))
            row.addWidget(cb, 1)
            row.addWidget(QLabel("머리 위:"))
            row.addWidget(combo, 1)
            v.addLayout(row)
        self.pack_on, self.pack_count, self.pack_rows = {}, {}, {}
        for sp in PACK_SPECIES:
            self._build_pack_group(v, cfg, sp)
        self.poch_on, self.poch_count = self.pack_on["pochacco"], self.pack_count["pochacco"]
        self.poch_rows = self.pack_rows["pochacco"]
        hint = QLabel("퇴근 타이머는 한 캐릭터만 들 수 있어요. 새로 고르면 그 캐릭터가 갖고, 먼저 갖고 있던 캐릭터는 포스트잇이 됩니다.")
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
        self.follow_on = QCheckBox("내가 키보드를 칠 때만 함께 키보드를 치기")
        self.follow_on.setChecked(bool(fo["enabled"]))
        self.follow_sec = QSpinBox()
        self.follow_sec.setRange(2, 600)
        self.follow_sec.setValue(int(fo["idle_seconds"]))
        self.follow_sec.setSuffix(" 초")
        row = QHBoxLayout()
        row.addWidget(QLabel("키보드를 안 누르면 쉬기까지"))
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
        note = QLabel("키가 눌렸는지(언제 눌렸는지)만 확인합니다. 어떤 키인지·무엇을 입력했는지는 읽거나 저장하지 않고, 마우스 움직임은 보지 않아요.")
        note.setWordWrap(True)
        note.setObjectName("hint")
        self.follow_status = QLabel("")
        self.follow_status.setWordWrap(True)
        self.follow_status.setObjectName("hint")
        v.addWidget(self.follow_on)
        v.addLayout(row)
        v.addLayout(row2)
        v.addWidget(self.follow_status)
        v.addWidget(note)
        self._status_timer = QTimer(self)                          # 키를 눌러 보면 감지되는지 바로 확인할 수 있다
        self._status_timer.timeout.connect(self._refresh_follow_status)
        self._status_timer.start(300)
        self._refresh_follow_status()
        lay.addWidget(g)

        # 퇴근
        g = QGroupBox("퇴근 타이머")
        v = QVBoxLayout(g)
        co = cfg["clockout"]
        self.co_on = QCheckBox("퇴근 타이머 사용")
        self.co_on.setChecked(bool(co["enabled"]))
        self.co_time = TimeField(co["time"])
        self.red_min = QSpinBox()
        self.red_min.setRange(1, 120)
        self.red_min.setValue(int(co["warn"][1]) if len(co.get("warn") or []) == 2 else 10)
        self.red_min.setSuffix(" 분 전")
        row = QHBoxLayout()
        row.addWidget(QLabel("퇴근 시각"))
        row.addWidget(self.co_time)
        row.addWidget(QLabel("(키보드로 입력: 1830)"))
        row.addStretch(1)
        row_red = QHBoxLayout()
        row_red.addWidget(QLabel("글자가 빨갛게 바뀌는 때"))
        row_red.addWidget(self.red_min)
        row_red.addStretch(1)
        self.co_days = []
        days = QHBoxLayout()
        for i, name in enumerate(DAY_LABELS):
            cb = QCheckBox(name)
            cb.setChecked(i in co["days"])
            self.co_days.append(cb)
            days.addWidget(cb)
        self.co_warn = QCheckBox("임박하면 색으로 알림 (주황→빨강)")
        self.co_warn.setChecked(bool(co["warn"]))
        v.addWidget(self.co_on)
        v.addLayout(row)
        v.addLayout(row_red)
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
        self.credit = credit
        credit.setObjectName("hint")
        credit.setAlignment(Qt.AlignCenter)
        outer.addWidget(credit)

        for cb in self.show_cb.values():
            cb.toggled.connect(lambda _c: self._refresh_credit())
        self._refresh_credit()
        scr = QApplication.primaryScreen().availableGeometry()
        need = content.minimumSizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 70   # 가로로 넘기지 않고 다 보이게
        self.resize(min(int(scr.width() * 0.95), max(580, need)), max(420, min(900, int(scr.height() * 0.88))))
        self.setMinimumWidth(min(int(scr.width() * 0.95), max(560, need - 20)))

    # -- 크기 ---------------------------------------------------------------
    def _build_pack_group(self, v, cfg, sp):
        """포차코·키티도 치이카와·하치와레·우사기와 같은 목록에서 고른다: 이름 체크 + 마리 수(1~4) + 마리별 머리 위 물건."""
        ids = PACK_IDS[sp]
        on_cb = QCheckBox(PACK_LABEL[sp])
        count = QSpinBox()
        count.setRange(1, len(ids))
        count.setSuffix(" 마리")
        rows = {}
        self.pack_on[sp], self.pack_count[sp], self.pack_rows[sp] = on_cb, count, rows
        if not self.pack_ready[sp]:
            row = QHBoxLayout()
            on_cb.setEnabled(False)
            row.addWidget(on_cb, 1)
            row.addWidget(QLabel(f"({PACK_LABEL[sp]} 그림 팩이 없어요 — README의 '포차코·키티 팩' 참고)"))
            v.addLayout(row)
            count.hide()
            return
        on = [c for c in ids if c in cfg["enabled"]]
        on_cb.setChecked(bool(on))
        count.setValue(max(1, len(on)))
        row = QHBoxLayout()
        row.addWidget(on_cb, 1)
        row.addWidget(QLabel("마리 수"))
        row.addWidget(count)
        v.addLayout(row)
        for k, ch in enumerate(ids):
            box = QWidget()
            r = QHBoxLayout(box)
            r.setContentsMargins(18, 0, 0, 0)
            combo = QComboBox()
            for key, label in CARRY_CHOICES:
                combo.addItem(label, key)
            combo.setCurrentIndex(max(0, [k_ for k_, _ in CARRY_CHOICES].index(cfg["carry"].get(ch, "memo"))))
            self.carry_cb[ch] = combo
            combo.currentIndexChanged.connect(lambda _i, c=ch: self._carry_changed(c))
            self.show_cb[ch] = QCheckBox(self)                       # 화면에는 보이지 않는 표시용 상태(위의 이름·마리 수에서 정해진다)
            self.show_cb[ch].hide()
            r.addWidget(QLabel(f"{CHAR_LABEL[ch]}  머리 위:"))
            r.addWidget(combo, 1)
            rows[ch] = box
            v.addWidget(box)
        on_cb.toggled.connect(lambda _c, s=sp: self._sync_pack(s))
        count.valueChanged.connect(lambda _v, s=sp: self._sync_pack(s))
        self._sync_pack(sp)

    def _carry_changed(self, ch):
        """퇴근 타이머를 고르면 그 캐릭터가 갖는다(다른 캐릭터에 있던 퇴근 타이머는 포스트잇으로 바뀐다)."""
        if self.carry_cb[ch].currentData() != "clock":
            return
        for other, cb in self.carry_cb.items():
            if other != ch and cb.currentData() == "clock":
                cb.blockSignals(True)
                cb.setCurrentIndex(max(0, [k for k, _ in CARRY_CHOICES].index("memo")))
                cb.blockSignals(False)

    def _sync_pack(self, sp):
        if not self.pack_ready.get(sp):
            return
        n = self.pack_count[sp].value() if self.pack_on[sp].isChecked() else 0
        for k, ch in enumerate(PACK_IDS[sp]):
            self.show_cb[ch].setChecked(k < n)
            self.pack_rows[sp][ch].setVisible(k < n)
            if ch in self.slider_rows:
                self.slider_rows[ch].setVisible(k < n)
        self.pack_count[sp].setEnabled(self.pack_on[sp].isChecked())
        self._refresh_credit()
        if getattr(self, "preview", None) is not None:
            self.preview.update()

    def _sync_pochacco(self, *_):
        self._sync_pack("pochacco")

    def _credit_text(self):
        parts = [COPYRIGHT_NOTICE]                                   # 치이카와(먹작귀) 표기는 항상 보인다
        for sp in PACK_SPECIES:
            if any(self.show_cb[c].isChecked() for c in PACK_IDS[sp] if c in self.show_cb):
                parts.append(PACK_CREDIT[sp])
        return "\n".join(parts) or COPYRIGHT_NOTICE

    def _refresh_credit(self):
        if getattr(self, "credit", None) is not None:
            self.credit.setText(self._credit_text())

    def _refresh_follow_status(self):
        import activity
        try:
            from build_info import BUILD
        except ImportError:
            BUILD = "dev"
        self.follow_status.setText(activity.describe(activity.idle_seconds()) + f"  (빌드 {BUILD})")

    def _enabled_chars(self):
        return [c for c in self.ids if c in self.show_cb and self.show_cb[c].isChecked()]

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
        for c in self.ids:
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
        for c in self.ids:
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
        enabled = [ch for ch in self.ids if ch in self.show_cb and self.show_cb[ch].isChecked()] or [CHARS[0]]
        carry_in = dict(self.cfg_carry)
        carry_in.update({ch: cb.currentData() for ch, cb in self.carry_cb.items()})
        carry = normalize_carry(carry_in, enabled)
        return {
            "follow": {"enabled": self.follow_on.isChecked(), "idle_seconds": self.follow_sec.value(), "away_minutes": self.away_min.value()},
            "enabled": enabled, "on_top": self.on_top.isChecked(), "autostart": self.autostart.isChecked(), "carry": carry,
            "scales": self.current_scales(),
            "clockout": {
                "enabled": self.co_on.isChecked(), "time": self.co_time.time().toString("HH:mm"),
                "days": [i for i, cb in enumerate(self.co_days) if cb.isChecked()],
                "warn": [max(30, self.red_min.value() + 20), self.red_min.value()] if self.co_warn.isChecked() else [],
            },
        }
