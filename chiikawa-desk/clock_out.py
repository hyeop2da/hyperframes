"""퇴근 시각 계산 (Qt 없음)."""
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta

OFF, FAR, WARN30, WARN10, NOW, OVER = "off", "far", "warn30", "warn10", "now", "over"


@dataclass
class Schedule:
    enabled: bool = True
    time: str = "18:00"                       # HH:MM
    days: tuple = (0, 1, 2, 3, 4)             # 월=0 … 일=6
    warn: tuple = (30, 10)                    # 몇 분 전에 단계가 바뀌는지
    skip_date: str = ""                       # 'YYYY-MM-DD' (오늘만 끄기)
    now_minutes: int = 5                      # 정각 연출 지속(분)


def parse_hhmm(s):
    try:
        h, m = str(s).split(":")
        return dtime(int(h), int(m))
    except (ValueError, TypeError):
        return dtime(18, 0)


def leave_dt(now: datetime, sch: Schedule):
    """오늘의 퇴근 시각. 꺼져 있거나 쉬는 요일이면 None."""
    if not sch.enabled or now.weekday() not in sch.days:
        return None
    if sch.skip_date == now.date().isoformat():
        return None
    return datetime.combine(now.date(), parse_hhmm(sch.time))


def status(now: datetime, sch: Schedule):
    """(단계, 남은 초) — 단계: off/far/warn30/warn10/now/over."""
    leave = leave_dt(now, sch)
    if leave is None:
        return OFF, 0.0
    left = (leave - now).total_seconds()
    w_far, w_near = (max(sch.warn), min(sch.warn)) if sch.warn else (0, 0)   # 알림을 끄면 임박 단계 없이 FAR
    if left > w_far * 60:
        return FAR, left
    if left > w_near * 60:
        return WARN30, left
    if left > 0:
        return WARN10, left
    if now < leave + timedelta(minutes=sch.now_minutes):
        return NOW, left
    return OVER, left


def format_left(seconds):
    """'1:23'(1시간 이상) / '23분' / '9:41'(10분 미만, 분:초)."""
    s = max(0, int(seconds))
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}"
    if s >= 600:
        return f"{s // 60}분"
    return f"{s // 60}:{s % 60:02d}"
