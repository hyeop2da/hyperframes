"""캐릭터별 행동 계획 (Qt 없음, 가짜 시계·고정 난수로 시험 가능).

* IdleActor   : 일하지 않을 때 쉬지 않고 계속 다른 동작을 이어간다.
                다른 캐릭터가 지금 하는 동작은 고르지 않고, 방금 한 동작도 곧바로 반복하지 않는다.
* TypingActor : 일할 때 키보드를 친다. 캐릭터마다 속도·컷 순서·쉬는 타이밍이 달라서 박자가 맞지 않는다.
컷 이름: '<캐릭터>_<포즈>'(base/focus/rest/cheer), '<캐릭터>_type<NN>', '<캐릭터>_idle<NN>'
"""
import random
from dataclasses import dataclass, field

import pack_map as pm


@dataclass
class Action:
    name: str
    plan: list                         # [(컷 이름, 초), ...]
    motion: dict = field(default_factory=dict)   # tilt(도) tilt_hz bob(키 대비 비율) bob_hz
    hop: bool = False                  # 시작할 때 통통 뜀
    weight: float = 1.0


def _seq(ch, items):
    return [(f"{ch}_{n}" if isinstance(n, str) else f"{ch}_idle{n:02d}", s) for n, s in items]


# 컷 번호는 frames/poses/_preview.png 의 '쉬는 컷' 줄 순서(1부터)
def build_repertoire(ch, available):
    """사용할 수 있는 컷만으로 행동 목록을 만든다."""
    A = []
    A.append(Action("sip", _seq(ch, [("rest", 4.0)]), {"bob": 0.006, "bob_hz": 0.5, "tilt": 1.5, "tilt_hz": 0.3}, weight=1.2))
    A.append(Action("cheer", _seq(ch, [("cheer", 2.2)]), {"bob": 0.004, "bob_hz": 2.0}, hop=True, weight=1.0))
    A.append(Action("sway", _seq(ch, [("base", 3.2)]), {"tilt": 5.0, "tilt_hz": 0.6, "bob": 0.004, "bob_hz": 0.6}, weight=1.3))
    A.append(Action("bounce", _seq(ch, [("base", 2.2)]), {"bob": 0.02, "bob_hz": 1.0, "tilt": 1.0, "tilt_hz": 0.6}, weight=0.9))
    A.append(Action("study", _seq(ch, [("focus", 3.5)]), {"bob": 0.006, "bob_hz": 1.4, "tilt": 2.0, "tilt_hz": 0.9}, weight=0.8))
    if ch == "chiikawa":
        A += [
            Action("blink", _seq(ch, [(1, 1.8), (2, 0.12), (3, 0.16), (2, 0.12), (1, 0.8)]), weight=1.4),
            Action("look-right", _seq(ch, [(1, 0.4), (5, 0.9), (6, 0.8), (5, 0.6), (1, 0.4)]), weight=1.2),
            Action("look-left", _seq(ch, [(1, 0.4), (7, 1.0), (10, 0.9), (7, 0.6), (1, 0.4)]), weight=1.2),
            Action("look-around", _seq(ch, [(1, 0.3), (5, 0.7), (8, 0.5), (7, 0.7), (10, 0.6), (1, 0.4)]), weight=1.1),
        ]
    elif ch == "hachiware":
        A += [
            Action("wave", _seq(ch, [(7, 0.5), (8, 0.6), (7, 0.5), (8, 0.6), (7, 0.4)]), {"tilt": 3.0, "tilt_hz": 1.2}, weight=1.3),
            Action("tilt-head", _seq(ch, [(1, 0.4), (3, 1.2), (6, 1.0), (1, 0.4)]), weight=1.2),
            Action("shy", _seq(ch, [(1, 0.3), (9, 1.6), (2, 0.5)]), {"tilt": 2.0, "tilt_hz": 0.8}, weight=1.0),
            Action("worry", _seq(ch, [(1, 0.3), (10, 0.8), (11, 0.9), (10, 0.7), (1, 0.4)]), weight=0.9),
            Action("shock", _seq(ch, [(12, 1.5), (1, 0.4)]), {"bob": 0.004, "bob_hz": 1.0}, weight=0.6),
            Action("smile", _seq(ch, [(2, 1.4), (5, 0.8)]), weight=1.1),
        ]
    elif ch == "usagi":
        A += [
            Action("point", _seq(ch, [(1, 0.3), (2, 1.4), (1, 0.4)]), weight=1.1),
            Action("arms-out", _seq(ch, [(3, 1.5), (4, 0.6), (3, 1.0)]), {"tilt": 2.5, "tilt_hz": 0.9}, weight=1.2),
            Action("wave", _seq(ch, [(4, 0.45), (5, 0.45), (4, 0.45), (5, 0.45), (4, 0.4)]), {"tilt": 3.0, "tilt_hz": 1.4}, weight=1.3),
            Action("dizzy", _seq(ch, [(6, 2.0)]), {"tilt": 6.0, "tilt_hz": 1.8}, weight=0.7),
            Action("sparkle", _seq(ch, [(7, 0.6), (8, 0.6), (9, 0.7), (8, 0.6)]), {"bob": 0.01, "bob_hz": 1.5}, hop=True, weight=1.0),
        ]
    elif ch == "kitty":
        i = lambda r, c: pm.idle((r, c))              # 시트의 칸(행, 열) → 쉬는 컷 번호 (키티 시트는 5번째 줄이 다르다: 놀람·울기)
        A += [
            Action("smile", _seq(ch, [(i(4, 3), 1.6), ("base", 0.5)]), weight=1.2),
            Action("wave", _seq(ch, [("base", 0.4), (i(1, 4), 1.5), ("base", 0.4)]), weight=1.2),
            Action("tremble", _seq(ch, [(i(1, 5), 1.6)]), weight=0.8),
            Action("shy", _seq(ch, [("base", 0.3), (i(1, 6), 1.8), ("base", 0.4)]), weight=1.0),
            Action("turn-around", _seq(ch, [(i(2, 1), 1.0), (i(2, 2), 0.9), (i(2, 3), 1.4), (i(2, 2), 0.8), ("base", 0.4)]), weight=1.1),
            Action("sweat", _seq(ch, [(i(2, 4), 1.2), (i(9, 3), 1.2)]), weight=0.9),
            Action("blush", _seq(ch, [(i(2, 6), 1.8)]), weight=0.8),
            Action("nap", _seq(ch, [(i(3, 3), 0.8), (i(3, 1), 2.0), (i(3, 2), 2.2), (i(3, 5), 1.4), (i(3, 6), 0.6), (i(3, 4), 1.0)]), weight=0.9),
            Action("sparkle", _seq(ch, [(i(4, 5), 0.9), ("cheer", 0.9), (i(4, 6), 0.9)]), hop=True, weight=1.0),
            Action("kick-ball", _seq(ch, [(i(5, 1), 0.6), (i(6, 3), 0.8), (i(5, 6), 0.6)]), weight=1.1),
            Action("surprise", _seq(ch, [("base", 0.3), (i(5, 2), 1.6), ("base", 0.4)]), weight=1.0),
            Action("tantrum", _seq(ch, [(i(5, 3), 0.9), (i(5, 4), 1.2), (i(5, 3), 0.8)]), weight=0.6),
            Action("tail-shake", _seq(ch, [(i(5, 5), 1.9)]), weight=0.8),
            Action("tiptoe", _seq(ch, [(i(6, 1), 0.6), (i(5, 6), 0.6), (i(6, 1), 0.6), (i(5, 6), 0.6)]), weight=0.9),
            Action("point", _seq(ch, [("base", 0.3), (i(6, 2), 1.6), ("base", 0.4)]), weight=1.1),
            Action("stretch", _seq(ch, [("base", 0.3), (i(6, 4), 1.7), ("base", 0.4)]), weight=0.9),
            Action("dizzy", _seq(ch, [(i(6, 5), 1.2), (i(6, 6), 1.3)]), weight=0.7),
            Action("grumpy", _seq(ch, [(i(8, 1), 0.6), (i(8, 3), 0.9), (i(9, 6), 0.9)]), weight=0.8),
            Action("cry", _seq(ch, [(i(8, 4), 0.8), (i(8, 5), 1.2), (i(8, 6), 1.2)]), weight=0.6),
            Action("sad", _seq(ch, [(i(9, 1), 1.2), (i(9, 4), 1.2), (i(9, 5), 1.0)]), weight=0.7),
            Action("bored", _seq(ch, [(i(9, 2), 2.2)]), weight=1.0),
            Action("love", _seq(ch, [(i(10, 2), 0.9), (i(10, 4), 1.2), (i(10, 5), 0.9)]), weight=0.9),
            Action("bliss", _seq(ch, [(i(10, 6), 1.8)]), weight=0.9),
        ]
    elif ch == "pochacco":
        i = lambda r, c: pm.idle((r, c))              # 시트의 칸(행, 열) → 쉬는 컷 번호
        A += [
            Action("blink", _seq(ch, [("base", 1.6), (i(1, 2), 0.14), ("base", 0.9)]), weight=1.4),
            Action("wink", _seq(ch, [("base", 0.6), (i(1, 3), 0.9), ("base", 0.6)]), weight=1.1),
            Action("smile", _seq(ch, [(i(4, 3), 1.6), ("base", 0.5)]), weight=1.2),
            Action("lean", _seq(ch, [("base", 0.4), (i(1, 4), 1.5), ("base", 0.4)]), weight=1.0),
            Action("tremble", _seq(ch, [(i(1, 5), 1.6)]), weight=0.8),
            Action("shy", _seq(ch, [("base", 0.3), (i(1, 6), 1.8), ("base", 0.4)]), weight=1.0),
            Action("turn-around", _seq(ch, [(i(2, 1), 1.0), (i(2, 2), 0.9), (i(2, 3), 1.4), (i(2, 2), 0.8), ("base", 0.4)]), weight=1.1),
            Action("sweat", _seq(ch, [(i(2, 4), 1.2), (i(9, 3), 1.2)]), weight=0.9),
            Action("blush", _seq(ch, [(i(2, 6), 1.8)]), weight=0.8),
            Action("nap", _seq(ch, [(i(3, 3), 0.8), (i(3, 1), 2.0), (i(3, 2), 2.2), (i(3, 5), 1.4), (i(3, 6), 0.6), (i(3, 4), 1.0)]), weight=0.9),
            Action("sparkle", _seq(ch, [(i(4, 5), 0.9), ("cheer", 0.9), (i(4, 6), 0.9)]), hop=True, weight=1.0),
            Action("kick-ball", _seq(ch, [(i(5, 1), 0.6), (i(6, 3), 0.8), (i(5, 6), 0.6)]), weight=1.1),
            Action("clap", _seq(ch, [(i(5, 2), 1.7)]), weight=1.0),
            Action("wave", _seq(ch, [(i(5, 3), 0.5), (i(5, 4), 0.5), (i(5, 3), 0.5), (i(5, 4), 0.5), ("base", 0.3)]), weight=1.3),
            Action("tail-wag", _seq(ch, [(i(5, 5), 1.9)]), weight=0.8),
            Action("tiptoe", _seq(ch, [(i(6, 1), 0.6), (i(5, 6), 0.6), (i(6, 1), 0.6), (i(5, 6), 0.6)]), weight=0.9),
            Action("point", _seq(ch, [("base", 0.3), (i(6, 2), 1.6), ("base", 0.4)]), weight=1.1),
            Action("dizzy", _seq(ch, [(i(6, 5), 1.2), (i(6, 6), 1.3)]), weight=0.7),
            Action("grumpy", _seq(ch, [(i(8, 1), 0.6), (i(8, 3), 0.9), (i(9, 6), 0.9)]), weight=0.8),
            Action("cry", _seq(ch, [(i(8, 4), 0.8), (i(8, 5), 1.2), (i(8, 6), 1.2)]), weight=0.6),
            Action("sad", _seq(ch, [(i(9, 1), 1.2), (i(9, 4), 1.2), (i(9, 5), 1.0)]), weight=0.7),
            Action("bored", _seq(ch, [(i(9, 2), 2.2)]), weight=1.0),
            Action("love", _seq(ch, [(i(10, 2), 0.9), (i(10, 4), 1.2), (i(10, 5), 0.9)]), weight=0.9),
            Action("bliss", _seq(ch, [(i(10, 6), 1.8)]), weight=0.9),
        ]
    out = []
    for a in A:
        if all(frame in available for frame, _ in a.plan):
            out.append(a)
    return out


class IdleActor:
    """쉬는 동안 '동작 → 잠깐 숨 돌리기 → 다른 동작'을 끝없이 이어간다."""

    def __init__(self, ch, available, rng=None, now=0.0):
        self.ch = ch
        self.rng = rng or random.Random()
        self.actions = build_repertoire(ch, available)
        self.base_frame = f"{ch}_base"
        self.current = None            # 지금 하는 Action (숨 돌리는 중이면 None)
        self.last_name = None
        self.t0 = now
        self._rest_until = now + self.rng.uniform(0.2, 2.5)     # 처음 시작 시점도 캐릭터마다 다르게
        self._hop_fired = False

    @property
    def name(self):
        return self.current.name if self.current else None

    def _pick(self, peers):
        free = [a for a in self.actions if a.name not in peers and a.name != self.last_name]
        pool = free or [a for a in self.actions if a.name != self.last_name] or self.actions
        return self.rng.choices(pool, weights=[a.weight for a in pool])[0]

    def update(self, now, peers=()):
        """→ (컷 이름, 모션 dict, 방금 통통 뛰기를 시작했는가)"""
        peers = set(peers)
        if self.current is None:
            if now >= self._rest_until and self.actions:
                self.current = self._pick(peers)
                self.t0 = now
                self._hop_fired = False
            else:
                return self.base_frame, {"bob": 0.003, "bob_hz": 0.4}, False
        a = self.current
        t = now - self.t0
        total = sum(s for _, s in a.plan)
        if t >= total:
            self.last_name, self.current = a.name, None
            self._rest_until = now + self.rng.uniform(0.7, 2.8)
            return self.base_frame, {"bob": 0.003, "bob_hz": 0.4}, False
        frame, acc = a.plan[-1][0], 0.0
        for f, s in a.plan:
            acc += s
            if t < acc:
                frame = f
                break
        hop = False
        if a.hop and not self._hop_fired:
            self._hop_fired, hop = True, True
        return frame, a.motion, hop


class TypingActor:
    """키보드 치기: 캐릭터마다 박자·컷 순서·숨 돌리는 타이밍이 다르다."""

    TEMPO = {"chiikawa": 1.0, "hachiware": 0.86, "usagi": 1.22, "pochacco": 1.05, "kitty": 0.95}

    def __init__(self, ch, frames, rng=None, now=0.0, bias=1.0):
        """frames: [(컷 이름, 바쁜 컷 여부), ...]"""
        self.ch = ch
        self.rng = rng or random.Random()
        self.calm = [n for n, busy in frames if not busy] or [n for n, _ in frames]
        self.busy = [n for n, busy in frames if busy] or self.calm
        self.bias = bias                                 # 같은 그림의 여러 마리가 박자를 다르게
        self.tempo = self.TEMPO.get(ch, 1.0) * bias * self.rng.uniform(0.92, 1.08)
        self._next = now + self.rng.uniform(0.0, 0.1)
        self._retempo = now + self.rng.uniform(3, 6)
        self.frame = self.calm[0]

    def hit(self, now, intensity):
        """키를 누른 순간: 바로 다음 손 모양으로 바꾼다(자동 전환은 잠깐 미룬다)."""
        inten = max(0.0, min(1.0, intensity))
        pool = self.busy if self.rng.random() < 0.25 + 0.5 * inten else self.calm
        pool = [f for f in pool if f != self.frame] or [f for f in self.calm + self.busy if f != self.frame] or pool
        self.frame = self.rng.choice(pool)
        self._next = now + 0.45
        return self.frame

    def update(self, now, intensity):
        """→ 지금 보여줄 컷 이름"""
        if now >= self._retempo:                                  # 박자가 조금씩 흔들림
            self.tempo = self.TEMPO.get(self.ch, 1.0) * self.bias * self.rng.uniform(0.85, 1.15)
            self._retempo = now + self.rng.uniform(3, 6)
        if now >= self._next:
            inten = max(0.0, min(1.0, intensity))
            if inten < 0.45 and self.rng.random() < 0.12:         # 생각하며 잠깐 손을 멈춤
                self.frame = self.calm[0]
                self._next = now + self.rng.uniform(0.45, 1.0)
            else:
                pool = self.busy if self.rng.random() < 0.12 + 0.75 * inten else self.calm
                pool = [f for f in pool if f != self.frame] or pool
                self.frame = self.rng.choice(pool)
                hold = 0.42 / (self.tempo * (0.7 + 0.8 * inten))               # 컷 전환을 느긋하게
                self._next = now + hold * self.rng.uniform(0.8, 1.6)
        return self.frame
