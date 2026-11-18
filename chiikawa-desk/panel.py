"""설정 창. (타이머·퇴근 시계는 머리 위 물건이 되었고, 말풍선은 쓰지 않는다)"""
from PyQt5.QtCore import Qt, QTime, QTimer
from PyQt5.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QSpinBox, QTimeEdit, QVBoxLayout,
)

from pet import CHAR_LABEL, CHARS

DAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
CARRY_CHOICES = [("memo", "포스트잇"), ("timer", "집중 타이머"), ("clock", "퇴근 시계"), ("none", "없음")]


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
    def __init__(self, cfg, probe, reactor, parent=None):
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.probe, self.reactor = probe, reactor
        lay = QVBoxLayout(self)

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
        hint.setStyleSheet("color:#7b7562;")
        v.addWidget(hint)
        self.leader = QComboBox()
        for ch in CHARS:
            self.leader.addItem(CHAR_LABEL[ch], ch)
        self.leader.setCurrentIndex(max(0, CHARS.index(cfg["leader"]) if cfg["leader"] in CHARS else 0))
        row = QHBoxLayout()
        row.addWidget(QLabel("작업을 가장 먼저 알아채는 캐릭터"))
        row.addWidget(self.leader)
        v.addLayout(row)
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

        # 작업 반응
        g = QGroupBox("내 작업에 반응하기")
        v = QVBoxLayout(g)
        self.react = QCheckBox("다른 프로그램에서 작업할 때도 캐릭터가 함께 키보드를 두드리기")
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
        carry = normalize_carry({ch: self.carry_cb[ch].currentData() for ch in CHARS}, enabled)
        return {
            "focus_min": self.focus_min.value(), "rest_min": self.rest_min.value(),
            "react": self.react.isChecked(), "enabled": enabled, "leader": leader, "on_top": self.on_top.isChecked(),
            "carry": carry,
            "clockout": {
                "enabled": self.co_on.isChecked(), "time": self.co_time.time().toString("HH:mm"),
                "days": [i for i, cb in enumerate(self.co_days) if cb.isChecked()],
                "warn": [30, 10] if self.co_warn.isChecked() else [],
            },
        }
