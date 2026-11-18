"""집중/휴식 타이머 엔진 (Qt 없음, 가짜 시계로 시험 가능).

* 남은 시간은 '종료 시각(end_at)'으로 계산한다 → 앱 재시작·절전 복귀에도 정확.
* 입력 활동으로 시작/정지하지 않는다(이 모듈은 활동을 전혀 모른다).
"""
import time

FOCUS, REST = "focus", "rest"
IDLE, RUNNING, PAUSED, DONE = "idle", "running", "paused", "done"


class PomodoroTimer:
    def __init__(self, focus_min=25, rest_min=5, clock=time.time):
        self.clock = clock
        self.focus_min = focus_min
        self.rest_min = rest_min
        self.phase = FOCUS
        self.status = IDLE
        self.end_at = 0.0          # 실행 중일 때 종료 시각(epoch 초)
        self.paused_left = 0.0     # 일시정지 때 남은 초

    # -- 조회 ---------------------------------------------------------------
    def duration(self, phase=None):
        return (self.focus_min if (phase or self.phase) == FOCUS else self.rest_min) * 60.0

    def remaining(self):
        if self.status == RUNNING:
            left = self.end_at - self.clock()
            return max(0.0, min(left, self.duration() + 1.0))   # 시계가 거꾸로 간 이상값 제한
        if self.status == PAUSED:
            return self.paused_left
        if self.status == DONE:
            return 0.0
        return self.duration()

    # -- 조작 ---------------------------------------------------------------
    def start_focus(self):
        self.phase, self.status = FOCUS, RUNNING
        self.end_at = self.clock() + self.duration(FOCUS)

    def start_rest(self):
        self.phase, self.status = REST, RUNNING
        self.end_at = self.clock() + self.duration(REST)

    def pause(self):
        if self.status == RUNNING:
            self.paused_left = self.remaining()
            self.status = PAUSED

    def resume(self):
        if self.status == PAUSED:
            self.status = RUNNING
            self.end_at = self.clock() + self.paused_left

    def reset(self):
        self.phase, self.status = FOCUS, IDLE
        self.end_at = self.paused_left = 0.0

    def tick(self):
        """종료 시각이 지났으면 완료 처리하고 완료한 단계('focus'/'rest')를 돌려준다."""
        if self.status == RUNNING and self.clock() >= self.end_at:
            finished = self.phase
            if finished == FOCUS:
                self.status = DONE          # 응원 → 휴식 시작 버튼 대기
            else:
                self.reset()                # 휴식 완료 → 기본
            return finished
        return None

    # -- 저장/복원 ----------------------------------------------------------
    def to_dict(self):
        return dict(phase=self.phase, status=self.status, end_at=self.end_at, paused_left=self.paused_left,
                    focus_min=self.focus_min, rest_min=self.rest_min)

    def restore(self, d):
        """저장된 상태를 복원. 자리를 비운 사이 끝났다면 완료 처리하고 단계를 돌려준다."""
        try:
            self.focus_min = int(d.get("focus_min", self.focus_min))
            self.rest_min = int(d.get("rest_min", self.rest_min))
            self.phase = d.get("phase", FOCUS) if d.get("phase") in (FOCUS, REST) else FOCUS
            self.status = d.get("status", IDLE) if d.get("status") in (IDLE, RUNNING, PAUSED, DONE) else IDLE
            self.end_at = float(d.get("end_at", 0.0))
            self.paused_left = float(d.get("paused_left", 0.0))
        except (TypeError, ValueError):
            self.reset()
            return None
        return self.tick()
