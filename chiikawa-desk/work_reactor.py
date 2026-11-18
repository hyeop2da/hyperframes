"""'내 작업에 반응하기' 엔진 (Qt 없음, 가짜 시계로 시험 가능).

입력은 오직 두 가지 숫자뿐이다.
  * idle_ms        : 운영체제가 알려 주는 '마지막 입력 후 경과 ms'
  * pointer_moved  : 직전 샘플 이후 포인터 좌표가 바뀌었는지
→ 글자·키 종류·클립보드·프로그램 이름은 알 수도, 저장할 수도 없다.
메모리에는 최근 40초분의 '1초 단위 활동 점수'만 둔다(디스크에는 쓰지 않음).

상태: idle → focus(작업 시작) → together(함께 일하기) → (45초 무활동) → idle
"""
import random
from dataclasses import dataclass

IDLE, FOCUS, TOGETHER = "idle", "focus", "together"


@dataclass
class ReactorConfig:
    start_window: int = 10          # 최근 N초 중
    start_score: float = 3.0        #   활동 점수 합이 이 이상이고
    start_bins: int = 3             #   활동이 있었던 초가 이 개수 이상 → 집중 시작
    together_window: int = 30       # 최근 30초 중
    together_score: float = 10.0    #   활동 점수 합이 이 이상 → 함께 일하기
    idle_off_s: float = 45.0        # 이 시간 입력이 없으면 가라앉음
    resume_window: int = 5          # 가라앉은 직후엔 더 빨리 재개: 최근 5초 중
    resume_bins: int = 2            #   활동이 있었던 초가 2개 이상
    resume_memory_s: float = 600.0  #   (마지막으로 일한 뒤 10분 이내일 때만)
    pointer_weight: float = 0.5     # 포인터 이동만 있는 초의 가중치(입력=1.0)
    attack_per_s: float = 1.0       # 움직임 강도가 오르는 속도(약 1초)
    decay_per_s: float = 0.1        # 내려가는 속도(약 10초)
    nod_min_s: float = 40.0         # 말 없는 끄덕임 간격
    nod_max_s: float = 90.0
    hop_min_s: float = 120.0        # 가볍게 뛰는 응원 간격(최소 2분)
    hop_max_s: float = 240.0


class WorkReactor:
    def __init__(self, cfg=None, rng=None):
        self.cfg = cfg or ReactorConfig()
        self.rng = rng or random.Random()
        self.state = IDLE
        self.intensity = 0.0
        self._bins = {}                 # {초: 가중치}
        self._last_input_t = -1e9
        self._last_update = None
        self._last_engaged = -1e9
        self._next_nod = self._next_hop = 0.0

    # -- 입력 --------------------------------------------------------------
    def feed(self, now, idle_ms, pointer_moved=False):
        """0.25초마다 호출. idle_ms 가 None 이면(감지 불가) 무시."""
        if idle_ms is None:
            return
        input_t = now - idle_ms / 1000.0
        if input_t > self._last_input_t + 0.02:         # 새 입력이 있었다
            self._last_input_t = input_t
            sec = int(input_t)
            w = self.cfg.pointer_weight if pointer_moved else 1.0
            self._bins[sec] = max(self._bins.get(sec, 0.0), w)
        for s in [s for s in self._bins if s < int(now) - 40]:
            del self._bins[s]

    def idle_seconds(self, now):
        return now - self._last_input_t

    def _score(self, now, window):
        lo = int(now) - window + 1
        return sum(w for s, w in self._bins.items() if s >= lo)

    def _count(self, now, window):
        lo = int(now) - window + 1
        return sum(1 for s in self._bins if s >= lo)

    # -- 갱신 --------------------------------------------------------------
    def update(self, now):
        """상태를 갱신하고 이벤트 목록을 돌려준다: focus_start / together_start / settle / nod / hop."""
        c, events = self.cfg, []
        idle_s = self.idle_seconds(now)

        if self.state == IDLE:
            recent = (now - self._last_engaged) < c.resume_memory_s
            if recent:
                go = self._count(now, c.resume_window) >= c.resume_bins
            else:
                go = self._score(now, c.start_window) >= c.start_score and self._count(now, c.start_window) >= c.start_bins
            if go:
                self.state = FOCUS
                events.append("focus_start")
        else:
            self._last_engaged = now
            if idle_s >= c.idle_off_s:
                self.state = IDLE
                events.append("settle")
            elif self.state == FOCUS and self._score(now, c.together_window) >= c.together_score:
                self.state = TOGETHER
                events.append("together_start")
                self._next_nod = now + self.rng.uniform(c.nod_min_s, c.nod_max_s)
                self._next_hop = now + self.rng.uniform(c.hop_min_s, c.hop_max_s)
            if self.state == TOGETHER:
                if now >= self._next_hop:
                    events.append("hop")
                    self._next_hop = now + self.rng.uniform(c.hop_min_s, c.hop_max_s)
                    self._next_nod = max(self._next_nod, now + c.nod_min_s)
                elif now >= self._next_nod:
                    events.append("nod")
                    self._next_nod = now + self.rng.uniform(c.nod_min_s, c.nod_max_s)

        # 움직임 강도: 활동이 있으면 빠르게 오르고 없으면 서서히 내려간다
        dt = 0.0 if self._last_update is None else max(0.0, now - self._last_update)
        self._last_update = now
        target = 0.0 if self.state == IDLE else min(1.0, self._score(now, 4) / 3.0)
        if target > self.intensity:
            self.intensity = min(target, self.intensity + c.attack_per_s * dt)
        else:
            self.intensity = max(target, self.intensity - c.decay_per_s * dt)
        return events
