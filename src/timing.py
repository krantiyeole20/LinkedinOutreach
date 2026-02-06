"""
Poisson-distributed intra-day timing with time-varying rate function.
"""

import random
from datetime import time, datetime, timedelta
from typing import List, Optional

import structlog

from config.settings import settings

logger = structlog.get_logger()

# Time windows and relative rates (piecewise)
_RATE_WINDOWS = [
    (time(9, 0), time(10, 0), "TIMING_RATE_MORNING_WARMUP", 0.6),
    (time(10, 0), time(12, 0), "TIMING_RATE_MID_MORNING", 1.3),
    (time(12, 0), time(13, 0), "TIMING_RATE_LUNCH_DIP", 0.8),
    (time(13, 0), time(15, 0), "TIMING_RATE_AFTERNOON_PEAK", 1.2),
    (time(15, 0), time(17, 0), "TIMING_RATE_AFTERNOON_WIND", 0.7),
    (time(17, 0), time(18, 0), "TIMING_RATE_END_OF_DAY", 0.4),
]


def _rate_at(t: time) -> float:
    for start, end, attr, default in _RATE_WINDOWS:
        if start <= t < end:
            return getattr(settings, attr, default)
    return 0.4


def _max_rate() -> float:
    return max(
        getattr(settings, attr, default)
        for _, _, attr, default in _RATE_WINDOWS
    )


def _time_to_minutes(t: time) -> int:
    return t.hour * 60 + t.minute


def _minutes_to_time(minutes: int) -> time:
    h = minutes // 60
    m = minutes % 60
    return time(h, m)


def generate_daily_timestamps(
    n: int,
    operating_start: Optional[time] = None,
    operating_end: Optional[time] = None,
) -> List[time]:
    """
    Non-homogeneous Poisson process with time-varying rate.
    Uses thinning: generate candidate times, accept/reject based on rate(t)/max_rate.
    Adds per-timestamp jitter of +/- 5 minutes.
    Enforces minimum gap of 3 minutes between consecutive timestamps.
    """
    if n <= 0:
        return []

    start = operating_start or getattr(
        settings, "OPERATING_START", time(9, 0)
    )
    end = operating_end or getattr(settings, "OPERATING_END", time(18, 0))
    min_gap = getattr(settings, "TIMING_MIN_GAP_MINUTES", 3)
    jitter_min = getattr(settings, "TIMING_JITTER_MINUTES", 5)

    start_min = _time_to_minutes(start)
    end_min = _time_to_minutes(end)
    window_min = end_min - start_min
    if window_min <= 0:
        logger.warning("invalid_operating_window", start=start, end=end)
        return [start] * n

    max_rate = _max_rate()
    if max_rate <= 0:
        max_rate = 1.0

    candidates = []
    max_attempts = n * 100
    attempts = 0
    while len(candidates) < n and attempts < max_attempts:
        attempts += 1
        u = random.random()
        m = int(start_min + u * window_min)
        m = max(start_min, min(end_min - 1, m))
        t = _minutes_to_time(m)
        rate = _rate_at(t)
        if random.random() <= rate / max_rate:
            j = random.randint(-jitter_min, jitter_min)
            m_j = m + j
            m_j = max(start_min, min(end_min - 1, m_j))
            candidates.append(_minutes_to_time(m_j))

    if len(candidates) < n:
        logger.warning(
            "timing_sampling_insufficient",
            wanted=n,
            got=len(candidates),
        )
        while len(candidates) < n:
            u = random.random()
            m = int(start_min + u * window_min)
            m = max(start_min, min(end_min - 1, m))
            candidates.append(_minutes_to_time(m))

    candidates.sort(key=_time_to_minutes)

    result = []
    last_min = -999
    for t in candidates[:n]:
        m = _time_to_minutes(t)
        if m - last_min < min_gap:
            m = last_min + min_gap
            if m >= end_min:
                m = end_min - 1
            t = _minutes_to_time(m)
        last_min = m
        result.append(t)

    result.sort(key=_time_to_minutes)
    return result
