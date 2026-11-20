"""캐릭터 한 마리 = 투명 창 하나.

* 모드 3가지
    idle   : 쉬는 동안 쉬지 않고 다른 동작을 이어감(IdleActor) — 다른 캐릭터가 하는 동작은 피한다
    type   : 키보드를 두드림(TypingActor) — 캐릭터마다 박자·컷 순서가 다름
    static : 포즈 한 장(집중/휴식/응원) + 작은 움직임
* 모든 움직임은 '그리기 변환'으로 처리하고, 클릭 영역(마스크)은 컷이 바뀔 때만 갱신한다.
* 끌어서 옮길 수 있다(Shift 를 누르고 끌면 모두 함께).
"""
import json
import math
import random
import re
from pathlib import Path

from PyQt5.QtCore import QPoint, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap, QRegion, QTransform
from PyQt5.QtWidgets import QWidget

import behaviors as bh

POSES = ("base", "focus", "rest", "cheer")
CHARS = ("chiikawa", "hachiware", "usagi")                       # 기본으로 들어 있는 캐릭터
PACK_SPECIES = ("pochacco", "kitty")                              # 내 PC의 팩에서 불러오는 선택 캐릭터(포차코·키티)
PACK_LABEL = {"pochacco": "포차코", "kitty": "키티"}
PACK_IDS = {sp: (sp, sp + "2", sp + "3", sp + "4") for sp in PACK_SPECIES}   # 같은 그림을 최대 4마리까지(마리마다 따로 움직임)
POCHACCO_IDS = PACK_IDS["pochacco"]
KITTY_IDS = PACK_IDS["kitty"]
ALL_CHARS = CHARS + POCHACCO_IDS + KITTY_IDS
CHAR_LABEL = {"chiikawa": "치이카와", "hachiware": "하치와레", "usagi": "우사기"}
for _sp, _ids in PACK_IDS.items():
    for _k, _id in enumerate(_ids):
        CHAR_LABEL[_id] = PACK_LABEL[_sp] + ("" if _k == 0 else f" {_k + 1}")
# 마리마다 키보드 박자를 다르게(같은 그림이어도 손이 같이 움직이지 않도록)
TEMPO_BIAS = {_id: (1.0, 0.88, 1.14, 0.94)[_k] for _ids in PACK_IDS.values() for _k, _id in enumerate(_ids)}


def species(ch):
    """마리 이름 → 그림 이름(포차코 2·3·4 는 모두 'pochacco' 그림을 쓴다)."""
    return re.sub(r"\d+$", "", str(ch))


SCALE_MIN, SCALE_MAX = 0.08, 3.0
SLIDE_MAX = 0.13                 # 퇴근 임박: 의자에서 흘러내리는 깊이(캔버스 높이 대비)
SLIDE_PERIOD = 9.0               # 내려갔다 올라오는 한 번의 길이(초)
SLIDE_TILT = 3.5                 # 흘러내리며 뒤로 살짝 기대는 각도(도)
CHAIR_FADE = 2.2                 # 책상이 사라지고 의자가 나타나는 속도(초당)
SIZE_PRESETS = [("초소형", 0.12), ("아주 작게", 0.2), ("작게", 0.3), ("조금 작게", 0.4),
                ("보통", 0.5), ("크게", 0.8), ("아주 크게", 1.1)]


# 책상·키보드를 비스듬한 각도로 그린 컷: 쓰면 책상이 휙 움직이는 것처럼 보여서 키보드 치기에서 뺀다
ANGLED_TYPING = {"chiikawa_type08", "hachiware_type08",
                 "usagi_type04", "usagi_type05", "usagi_type06"}      # 우사기는 팔이 셋으로 보이는 컷(키보드에 두 팔 + 한 팔 더)


class PoseBank:
    """frames/poses/*.png 를 읽어 (크기별) 캐시해 두는 저장소. 컷은 '이름'으로 찾는다."""

    def __init__(self, pose_dir, pack_dir=None):
        """pack_dir: 내 PC 안에 둔 추가 캐릭터 팩 폴더(하나 또는 여러 개: 포차코·키티). 폴더가 없으면 건너뛴다."""
        pose_dir = Path(pose_dir)
        meta = json.loads((pose_dir / "manifest.json").read_text(encoding="utf-8"))
        self.cw, self.ch = meta["canvas"]
        self._top, self.typing, self.idle, self.tea, self._raw = {}, {}, {}, {}, {}
        self._load(pose_dir, meta)
        self.pack_error = ""
        packs = [] if pack_dir is None else (list(pack_dir) if isinstance(pack_dir, (list, tuple)) else [pack_dir])
        for pd in packs:
            if pd is None or not (Path(pd) / "manifest.json").exists():
                continue
            try:
                pmeta = json.loads((Path(pd) / "manifest.json").read_text(encoding="utf-8"))
                if list(pmeta["canvas"]) != [self.cw, self.ch]:
                    raise ValueError("캔버스 크기가 달라요(팩을 다시 만들어 주세요)")
                self._load(Path(pd), pmeta)
            except (OSError, ValueError, KeyError) as exc:
                self.pack_error = str(exc)
        self.names = set(self._raw)
        self._pix, self._reg, self._desk, self._seat = {}, {}, {}, {}

    def desk_top(self, name):
        """키보드 컷에서 책상 윗면의 y(캔버스 픽셀). 책상이 없는 컷이면 None. (처음 한 번만 계산해 기억한다)"""
        if name in self._desk:
            return self._desk[name]
        top = None
        pm = self._raw.get(name)
        if pm is not None and "_type" in name:
            img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
            w, h = img.width(), img.height()
            for yy in range(h // 3, h):
                cnt = 0
                for xx in range(0, w, 2):
                    c = img.pixel(xx, yy)
                    r, g, b = (c >> 16) & 255, (c >> 8) & 255, c & 255
                    if (c >> 24) & 255 > 128 and r > g > b and 165 <= r <= 240 and 115 <= g <= 195 and 65 <= b <= 155 and r - b >= 55:
                        cnt += 1
                if cnt >= 18:
                    top = yy
                    break
        self._desk[name] = top
        return top

    def seat_geom(self, name):
        """책상 없는 앉은 모습용: 책상 윗면 바로 아래를 자르는 선(cut)과 그 위 몸 폭(x0~x1). 책상이 없는 컷이면 None."""
        top = self.desk_top(name)
        if top is None:
            return None
        g = self._seat.get(name)
        if g is None:
            img = self._raw[name].toImage().convertToFormat(QImage.Format_ARGB32)
            w = img.width()
            cut = top + 2
            xs = [x for y in range(max(0, cut - 10), cut) for x in range(w) if (img.pixel(x, y) >> 24) & 255 > 128]
            g = {"cut": cut, "x0": min(xs) if xs else w * 0.3, "x1": max(xs) if xs else w * 0.7}
            self._seat[name] = g
        return g

    def cut_pixmap(self, name, scale, dpr):
        """책상·키보드를 지운 그림(자르는 선 아래를 모두 투명하게). 크기별로 기억해 둔다."""
        g = self.seat_geom(name)
        key = (name, round(scale, 3), dpr, "cut")
        pm = self._pix.get(key)
        if pm is None:
            pm = self.pixmap(name, scale, dpr).copy()
            q = QPainter(pm)
            q.setCompositionMode(QPainter.CompositionMode_Clear)
            q.fillRect(QRectF(0, g["cut"] * scale, pm.width() / max(1.0, dpr) + 2, pm.height() / max(1.0, dpr) + 2), QColor(0, 0, 0, 0))
            q.end()
            self._pix[key] = pm
        return pm

    def _load(self, d, meta):
        self._top.update({k: v["bbox"][1] for k, v in meta.get("poses", {}).items()})   # 컷별 머리(귀) 꼭대기 y
        for c, v in meta.get("typing", {}).items():
            self.typing[c] = [(t["name"], bool(t["busy"])) for t in v if t["name"] not in ANGLED_TYPING]
        self.idle.update(meta.get("idle", {}))
        self.tea.update(meta.get("tea", {}))
        for name in meta.get("poses", {}):
            pm = QPixmap(str(d / f"{name}.png"))
            if not pm.isNull():
                self._raw[name] = pm

    def has_char(self, ch):
        return all(f"{ch}_{p}" in self.names for p in POSES)

    def raw(self, name):
        return self._raw[name]

    def head_top(self, name):
        return self._top.get(name, 0)

    def fixed_top(self, char):
        char = species(char)
        """머리 위 물건을 놓는 고정 높이: 기본·집중·휴식·키보드 컷 중 가장 높은 머리 꼭대기(컷이 바뀌어도 물건이 오르내리지 않는다)."""
        vals = [v for n, v in self._top.items()
                if n.startswith(char + "_") and "_idle" not in n and not n.endswith("_cheer") and n not in ANGLED_TYPING]
        return min(vals) if vals else 0

    def clear_cache(self):
        self._pix.clear()
        self._reg.clear()

    def pixmap(self, name, scale, dpr):
        key = (name, round(scale, 3), dpr)
        pm = self._pix.get(key)
        if pm is None:
            src = self._raw[name]
            size = QSize(max(1, round(src.width() * scale * dpr)), max(1, round(src.height() * scale * dpr)))
            pm = src.scaled(size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            self._pix[key] = pm
        return pm

    def region(self, name, scale):
        key = (name, round(scale, 3))
        reg = self._reg.get(key)
        if reg is None:
            src = self._raw[name]
            small = src.scaled(QSize(max(1, round(src.width() * scale)), max(1, round(src.height() * scale))),
                               Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            reg = QRegion(small.mask())
            self._reg[key] = reg
        return reg


class Pet(QWidget):
    clicked = pyqtSignal(object)           # 좌클릭(끌지 않음)
    context_requested = pyqtSignal(object)
    moved = pyqtSignal(object)
    drag_ended = pyqtSignal(object)
    group_step = pyqtSignal(object, object)          # (펫, 끈 만큼) — Shift+끌기: 나머지도 같이 옮김
    wheel_scaled = pyqtSignal(object, float, bool)   # (펫, 배율 변화, 전체 적용 여부)

    def __init__(self, char, bank, scale=0.5, opacity=0.85, on_top=True, seed=None, now=0.0):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if on_top:
            flags |= Qt.WindowStaysOnTopHint
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if hasattr(Qt, "WA_MacAlwaysShowToolWindow"):
            self.setAttribute(Qt.WA_MacAlwaysShowToolWindow, True)
        self.char, self.bank = char, bank
        self.rng = random.Random(seed if seed is not None else random.random())
        self.scale = min(SCALE_MAX, max(SCALE_MIN, scale))
        self.opacity = opacity
        self.mode = "idle"
        self.pose = "idle"                 # 시험·표시용 꼬리표: idle / type / base / focus / rest / cheer
        self.species = species(char)
        self.frame = f"{self.species}_base"
        self.intensity = 0.0
        self.peers = lambda: set()         # 다른 캐릭터가 지금 하는 동작 이름들
        self._idle = bh.IdleActor(self.species, bank.names, self.rng, now=now)
        self._tea_i, self._tea_next = 0, 0.0
        self._hurry, self._slide, self._slide_off = False, 0.0, self.rng.uniform(0.0, SLIDE_PERIOD)
        self._hold = False
        self._chair = 0.0                                      # 0 = 책상, 1 = 바퀴 의자(책상·키보드 없음)
        self._typer = None
        self._static_pose = "base"
        self._extra = {}
        self._phase = self.rng.uniform(0, 6.28)
        self._phase2 = self.rng.uniform(0, 6.28)
        self._t = now
        self._hop = None                   # (시작 시각, 높이 비율, 횟수, 한 번 뛰는 시간)
        self._hop_pending = False
        self._nod_t0 = None
        self._nod_pending = False
        self._hop_height = self.rng.uniform(0.03, 0.045)
        self._motion = (0.0, 0.0, 0.0)     # (세로 이동 px, 기울기°, 가로 이동 px)
        self._press = None
        self._last = QPoint()
        self._dragging = False
        self._apply_size()
        self.setWindowOpacity(self.opacity)

    # -- 크기·마스크 --------------------------------------------------------
    def _geom(self):
        cw, ch = self.bank.cw * self.scale, self.bank.ch * self.scale
        return cw, ch, max(3.0, cw * 0.08), max(4.0, ch * 0.10)      # 캔버스 w/h, 좌우 여백, 위 여백

    def _apply_size(self):
        cw, ch, padx, pady = self._geom()
        self.setFixedSize(int(round(cw + 2 * padx)), int(round(ch + pady)))
        self._refresh_mask()
        self.update()

    def _refresh_mask(self):
        cw, ch, padx, pady = self._geom()
        reg = self.bank.region(self.frame, self.scale).translated(int(padx), int(pady))
        up, side = int(pady * 0.9), int(padx * 0.6)
        reg = reg.united(reg.translated(0, -up)).united(reg.translated(-side, 0)).united(reg.translated(side, 0))
        self.setMask(reg)

    def set_scale(self, s):
        s = min(SCALE_MAX, max(SCALE_MIN, s))
        if abs(s - self.scale) < 1e-4:
            return
        g = self.geometry()
        cx, bottom = g.center().x(), g.bottom()                      # 아래 중앙 기준으로 크기 변경
        self.scale = s
        self._apply_size()
        self.move(cx - self.width() // 2, bottom + 1 - self.height())

    def set_opacity(self, v):
        self.opacity = v
        self.setWindowOpacity(1.0 if self.underMouse() else v)

    # -- 모드 ---------------------------------------------------------------
    def _set_frame(self, name):
        if name != self.frame and name in self.bank.names:
            self.frame = name
            self._refresh_mask()
            self.update()

    def set_idle(self):
        if self.mode != "idle":
            self.mode, self.pose = "idle", "idle"
            self._idle.current = None                    # 막 쉬기 시작: 곧바로 다른 동작으로
            self._idle._rest_until = self._t + self.rng.uniform(0.1, 1.2)

    def set_typing(self, intensity):
        self.intensity = intensity
        if self.mode != "type":
            self.mode, self.pose = "type", "type"
            frames = self.bank.typing.get(self.species) or []
            self._typer = bh.TypingActor(self.species, frames, random.Random(self.rng.random()), now=self._t,
                                         bias=TEMPO_BIAS.get(self.char, 1.0)) if frames else None
            if self._typer is None:                      # 키보드 컷이 없으면 집중 포즈로 대신
                self.set_static("focus", intensity)

    def set_static(self, pose, intensity=0.0):
        self.intensity = intensity
        if self.mode != "static" or self._static_pose != pose:
            self.mode, self.pose, self._static_pose = "static", pose, pose
            self._set_frame(f"{self.species}_{pose}")
            self._tea_i, self._tea_next = 0, self._t + self.rng.uniform(3.0, 6.0)

    # -- 움직임 -------------------------------------------------------------
    def hop(self):
        self._hop_pending = True          # 시작 시각은 다음 틱의 시각을 기준으로 잡는다(시계를 하나로 통일)

    def nod(self):
        self._nod_pending = True

    def busy(self):
        return (self._hop is not None or self._nod_t0 is not None or self._hop_pending or self._nod_pending
                or self.mode != "static" or self.intensity > 0.02 or bool(self._extra))

    def action_name(self):
        if self.mode == "idle":
            return self._idle.name
        return None

    def set_hold(self, on):
        """True 면 키보드 컷을 스스로 바꾸지 않고 차분한 컷 하나로 둔다(키를 누르면 그때만 바뀜)."""
        self._hold = bool(on)

    def set_hurry(self, on):
        """퇴근이 임박했다: 키보드를 치는 동안 의자에서 천천히 미끄러져 내려갔다 올라온다(책상은 그대로)."""
        self._hurry = bool(on)

    def slide_fraction(self, now):
        """0 = 앉은 자리, 1 = 가장 깊이 미끄러진 상태. 천천히 내려가 잠깐 머물고, 다시 올라와 한참 쉰다(마리마다 시작점이 다름)."""
        if not self._hurry or self.mode != "type":
            return 0.0
        u = (now + self._slide_off) % SLIDE_PERIOD

        def ease(x):
            x = max(0.0, min(1.0, x))
            return x * x * (3.0 - 2.0 * x)
        if u < 1.8:
            return ease(u / 1.8)
        if u < 3.8:
            return 1.0
        if u < 5.0:
            return 1.0 - ease((u - 3.8) / 1.2)
        return 0.0

    def key_hit(self, now):
        """내가 키를 누른 순간: 키보드 치는 손 모양을 바로 바꾼다."""
        if self.mode == "type" and self._typer is not None:
            self._set_frame(self._typer.hit(now, self.intensity))
            self.update()

    def tick(self, now, dt):
        """프레임·움직임을 갱신한다. 값이 바뀌면 True."""
        self._t = now
        if self._hop_pending:
            self._hop_pending = False
            self._hop = (now, self._hop_height * self.rng.uniform(0.8, 1.2), self.rng.choice((1, 2)), self.rng.uniform(0.45, 0.6))
        if self._nod_pending:
            self._nod_pending, self._nod_t0 = False, now
        extra = {}
        if self.mode == "static" and self._static_pose == "rest" and now >= self._tea_next:
            tea = self.bank.tea.get(self.species)                      # 오래 쉬는 중: 차 마시는 컷을 천천히 돌려 본다
            if tea:
                self._tea_i = (self._tea_i + 1) % len(tea)
                self._set_frame(tea[self._tea_i])
                self._tea_next = now + self.rng.uniform(4.0, 7.0)
            else:
                self._tea_next = now + 1e9
        if self.mode == "idle":
            frame, extra, hop = self._idle.update(now, self.peers())
            self._set_frame(frame)
            if hop:
                self.hop()
        elif self.mode == "type" and self._typer is not None:
            if self._hold:
                self._set_frame(self._typer.calm[0])                   # 키를 안 치는 동안은 앉아만 있는다
            else:
                self._set_frame(self._typer.update(now, self.intensity))
        inten = max(0.0, min(1.0, self.intensity))
        self._extra = extra
        typing = self.mode == "type"
        freq = 0.8 + 0.8 * inten                                       # 천천히
        self._phase += dt * freq * 6.2832
        self._phase2 += dt * 0.35 * 6.2832
        H = self.bank.ch * self.scale
        calm = 0.0 if typing else 0.35                                # 키보드를 칠 땐 몸·책상이 전혀 움직이지 않는다
        dy = -(0.003 * H) * math.sin(self._phase2) * (0.0 if typing else 1.0)   # 숨쉬기
        dy += -(0.016 * H * inten * calm) * abs(math.sin(self._phase))
        tilt = 2.6 * inten * calm * math.sin(self._phase * 0.5 + 0.8)
        dx = 0.7 * inten * calm * math.sin(self._phase * 1.5)
        if extra and not typing:                                       # 동작이 요구하는 움직임(느리고 작게)
            hz_t, hz_b = min(0.6, extra.get("tilt_hz", 0.5) * 0.5), min(0.7, extra.get("bob_hz", 0.5) * 0.45)
            tilt += 0.5 * extra.get("tilt", 0.0) * math.sin(2 * math.pi * hz_t * now + self._phase2)
            dy -= 0.5 * extra.get("bob", 0.0) * H * abs(math.sin(2 * math.pi * hz_b * now + self._phase2))
        if self._hop is not None and not typing:                       # 통통 뜀 (캐릭터마다 높이·횟수·속도가 다름)
            t0, h, count, per = self._hop
            t = max(0.0, now - t0)
            if t > per * count:
                self._hop = None
            else:
                dy -= h * H * abs(math.sin(math.pi * t / per))
        if self._nod_t0 is not None:                                   # 끄덕끄덕
            t = max(0.0, now - self._nod_t0)
            if t > 0.9:
                self._nod_t0 = None
            else:
                k = math.exp(-2.0 * t)
                tilt += 0.0
                dy += 0.0
        want = 1.0 if (self._hurry and self.mode == "type") else 0.0   # 퇴근 임박: 책상이 사라지고 의자가 나타난다
        if abs(self._chair - want) > 1e-3:
            step = CHAIR_FADE * max(0.0, dt)
            self._chair = min(want, self._chair + step) if want > self._chair else max(want, self._chair - step)
            self.update()
        slide = round(self.slide_fraction(now) * self._chair, 3)
        if slide != self._slide:
            self._slide = slide
            self.update()
        new = (round(dy, 2), round(tilt, 2), round(dx, 2))
        if new != self._motion:
            self._motion = new
            self.update()
            return True
        return False

    def swing(self):
        return self._motion[1]

    def _transform(self):
        cw, ch, padx, pady = self._geom()
        dy, tilt, dx = self._motion
        pivot = QPointF(padx + cw / 2, pady + ch)                     # 발끝 중앙
        t = QTransform()
        t.translate(dx, dy)
        t.translate(pivot.x(), pivot.y())
        t.rotate(tilt)
        t.translate(-pivot.x(), -pivot.y())
        return t, padx, pady

    def anchor_global(self):
        """머리 위 물건의 아래 중앙 좌표. 캐릭터가 숨 쉬듯 움직이거나 컷이 바뀌어도 **전혀 움직이지 않는다**(끌어서 옮길 때만 따라온다)."""
        cw, ch, padx, pady = self._geom()
        top = self.bank.fixed_top(self.species) * self.scale
        return self.mapToGlobal(QPoint(int(round(padx + cw / 2)), int(round(pady + top))))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        t, padx, pady = self._transform()
        p.setTransform(t)
        dpr = self.devicePixelRatioF()
        pm = self.bank.pixmap(self.frame, self.scale, dpr)
        pos = QPoint(int(round(padx)), int(round(pady)))
        geom = self.bank.seat_geom(self.frame) if self._chair > 0.001 and self.mode == "type" else None
        if geom is None:
            p.drawPixmap(pos, pm)
            return
        c = self._chair
        s = self.scale
        if c < 0.999:                                               # 책상이 서서히 사라진다
            p.setOpacity(1.0 - c)
            p.drawPixmap(pos, pm)
        p.setOpacity(c)
        cx = padx + (geom["x0"] + geom["x1"]) / 2.0 * s              # 몸 가운데
        seat_top = pady + (geom["cut"] - 4) * s
        seat_w = max((geom["x1"] - geom["x0"]) * 1.12, self.bank.cw * 0.40) * s
        seat_h = 0.075 * self.bank.ch * s
        self._paint_chair_back(p, cx, seat_top, seat_w)
        body = self.bank.cut_pixmap(self.frame, s, dpr)
        shift = self._slide * SLIDE_MAX * self.bank.ch * s           # 몸이 등받이를 타고 흘러내린다(뒤로 살짝 기댐)
        big = max(self.width(), self.height()) * 4
        p.save()
        p.setClipRect(0, -big, big, int(seat_top + 0.6 * seat_h) + big)
        p.translate(cx, seat_top)
        p.rotate(-SLIDE_TILT * self._slide)
        p.translate(-cx, -seat_top)
        p.drawPixmap(QPoint(pos.x(), pos.y() + int(round(shift))), body)
        p.restore()
        self._paint_chair_seat(p, cx, seat_top, seat_w, seat_h, pady + (self.bank.ch - 17) * s)
        p.setOpacity(1.0)

    @staticmethod
    def _paint_chair_back(p, cx, seat_top, seat_w):
        """의자 등받이(몸 뒤)."""
        w, h = seat_w * 0.74, seat_w * 0.66
        p.setPen(QPen(QColor("#6B7079"), max(1.0, seat_w * 0.018)))
        p.setBrush(QColor("#9AA0AA"))
        p.drawRoundedRect(QRectF(cx - w / 2, seat_top - h, w, h + seat_w * 0.05), seat_w * 0.12, seat_w * 0.12)

    @staticmethod
    def _paint_chair_seat(p, cx, seat_top, seat_w, seat_h, base_y):
        """앉는 판 · 기둥 · 바퀴 달린 다섯 갈래 받침(몸 앞)."""
        line = max(1.0, seat_w * 0.018)
        pole_w = seat_w * 0.075
        pole_top = seat_top + seat_h * 0.8
        p.setPen(QPen(QColor("#555A62"), line))
        p.setBrush(QColor("#7A808A"))
        p.drawRect(QRectF(cx - pole_w / 2, pole_top, pole_w, max(2.0, base_y - pole_top)))      # 기둥
        arm = QColor("#F3F4F6")
        for dx, dy in ((-0.52, 0.0), (-0.28, 0.035), (0.28, 0.035), (0.52, 0.0), (0.0, 0.05)):   # 받침 다리 5개(앞에서 본 모습)
            ex, ey = cx + dx * seat_w, base_y + dy * seat_w
            p.setPen(QPen(QColor("#9AA0A8"), seat_w * 0.07, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx, base_y - seat_w * 0.01), QPointF(ex, ey))
            p.setPen(QPen(arm, seat_w * 0.045, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx, base_y - seat_w * 0.01), QPointF(ex, ey))
            p.setPen(QPen(QColor("#40444B"), line))
            p.setBrush(QColor("#50555D"))
            p.drawEllipse(QPointF(ex, ey + seat_w * 0.03), seat_w * 0.036, seat_w * 0.036)          # 바퀴
        p.setPen(QPen(QColor("#6B7079"), line))
        p.setBrush(QColor("#B9BEC7"))
        p.drawRoundedRect(QRectF(cx - seat_w / 2, seat_top, seat_w, seat_h), seat_h * 0.5, seat_h * 0.5)   # 앉는 판

    # -- 마우스 -------------------------------------------------------------
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press, self._last, self._dragging = e.globalPos(), e.globalPos(), False
        elif e.button() == Qt.RightButton:
            self.context_requested.emit(self)

    def mouseMoveEvent(self, e):
        if self._press is None or not (e.buttons() & Qt.LeftButton):
            return
        if not self._dragging and (e.globalPos() - self._press).manhattanLength() > 5:
            self._dragging = True
        if self._dragging:
            step = e.globalPos() - self._last
            self._last = e.globalPos()
            if not step.isNull():
                self.move(self.pos() + step)
                if e.modifiers() & Qt.ShiftModifier:               # Shift+끌기: 모두 함께
                    self.group_step.emit(self, step)

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton or self._press is None:
            return
        was_drag = self._dragging
        self._press, self._dragging = None, False
        (self.drag_ended if was_drag else self.clicked).emit(self)

    def moveEvent(self, _e):
        self.moved.emit(self)

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if steps:
            self.wheel_scaled.emit(self, 1.1 ** steps, bool(e.modifiers() & Qt.ControlModifier))
        e.accept()

    def enterEvent(self, _e):
        self.setWindowOpacity(1.0)

    def leaveEvent(self, _e):
        self.setWindowOpacity(self.opacity)
