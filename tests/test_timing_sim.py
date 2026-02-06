"""
Timing distribution validation: verify timestamps look human-like.
Runnable standalone: python -m tests.test_timing_sim
"""

import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.timing import generate_daily_timestamps


def _time_to_minutes(t) -> int:
    return t.hour * 60 + t.minute


def run_timing_sim():
    """Generate many timestamp sets and analyze distribution."""
    n_sets = 1000
    n_per_day = 12
    hourly_counts = defaultdict(int)
    gaps = []
    min_gap_violations = 0
    min_gap_minutes = 3

    for _ in range(n_sets):
        timestamps = generate_daily_timestamps(n_per_day)
        for t in timestamps:
            hourly_counts[t.hour] += 1
        for i in range(1, len(timestamps)):
            prev = _time_to_minutes(timestamps[i - 1])
            curr = _time_to_minutes(timestamps[i])
            gap = curr - prev
            gaps.append(gap)
            if gap < min_gap_minutes and gap >= 0:
                min_gap_violations += 1

    print("\n" + "=" * 60)
    print("TIMING SIMULATION: Hourly density (should peak mid-morning/afternoon)")
    print("=" * 60)
    for h in range(9, 18):
        count = hourly_counts.get(h, 0)
        bar = "#" * (count // (n_sets or 1)) + " " * (50 - count // (n_sets or 1))
        print(f"  {h:02d}:00 | {bar} {count}")
    print("=" * 60)

    if gaps:
        avg_gap = sum(gaps) / len(gaps)
        print(f"\nInter-arrival time: avg={avg_gap:.1f} min, min={min(gaps)}, max={max(gaps)}")
    print(f"Minimum gap violations (< {min_gap_minutes} min): {min_gap_violations}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_timing_sim()
