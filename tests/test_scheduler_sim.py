"""
Monte Carlo coverage simulation: validate 100% profiles engaged within 14 days.
Runnable: python -m tests.test_scheduler_sim [--weeks N] [--runs N] [--failure-rate F] ...
"""

import argparse
import random
import sys
from collections import defaultdict
from datetime import datetime, date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scorer import score_all_profiles, select_for_day
from src.timing import generate_daily_timestamps


def make_synthetic_state(n_profiles: int = 100) -> list:
    """Create initial state for all profiles."""
    today = date.today()
    initial_engaged_date = today - timedelta(days=7)
    state = []
    for i in range(n_profiles):
        state.append({
            "linkedin_url": f"https://linkedin.com/in/user{i}",
            "name": f"User {i}",
            "last_engaged_date": initial_engaged_date.isoformat(),
            "status": "active",
            "consecutive_skips": 0,
            "engagement_count": 0,
        })
    return state


def simulate_week(
    state: list,
    failure_rate: float = 0.10,
    already_reacted_rate: float = 0.05,
    no_posts_rate: float = 0.05,
) -> dict:
    """
    Simulate one week: 7 days, ~80 engagements total.
    Returns per-profile days_since at end of week.
    """
    today = date.today()
    profile_last_engaged = {}
    for p in state:
        pid = p["linkedin_url"]
        led = p.get("last_engaged_date")
        if led:
            try:
                if isinstance(led, str):
                    d = datetime.fromisoformat(led.replace("Z", "+00:00")).date()
                else:
                    d = led
                profile_last_engaged[pid] = d
            except (ValueError, TypeError):
                profile_last_engaged[pid] = today - timedelta(days=7)
        else:
            profile_last_engaged[pid] = today - timedelta(days=7)

    budgets = [12, 11, 14, 10, 13, 10, 10]
    total_planned = sum(budgets)
    yesterday_urls = set()

    for day_offset in range(7):
        day_date = today + timedelta(days=day_offset)
        budget = budgets[day_offset] if day_offset < len(budgets) else 12

        state_copy = []
        for p in state:
            sc = dict(p)
            sc["last_engaged_date"] = (
                profile_last_engaged.get(p["linkedin_url"])
                and profile_last_engaged[p["linkedin_url"]].isoformat()
                or None
            )
            state_copy.append(sc)

        scored = score_all_profiles(state_copy, datetime.combine(day_date, datetime.min.time()))
        selected = select_for_day(scored, budget, yesterday_urls)
        yesterday_urls = {s.linkedin_url for s in selected}

        for sp in selected:
            outcome = random.random()
            if outcome < failure_rate:
                continue
            if outcome < failure_rate + already_reacted_rate:
                continue
            if outcome < failure_rate + already_reacted_rate + no_posts_rate:
                continue
            profile_last_engaged[sp.linkedin_url] = day_date

    return profile_last_engaged


def run_monte_carlo(
    weeks: int = 12,
    runs: int = 50,
    failure_rate: float = 0.10,
    already_reacted_rate: float = 0.05,
    no_posts_rate: float = 0.05,
):
    """Run Monte Carlo simulation."""
    n_profiles = 100
    coverage_buckets = defaultdict(int)
    worst_gaps = []

    for run in range(runs):
        state = make_synthetic_state(n_profiles)
        profile_max_gap = {p["linkedin_url"]: 0 for p in state}
        profile_last = {p["linkedin_url"]: None for p in state}
        today = date.today()

        for w in range(weeks):
            week_start = today + timedelta(weeks=w)
            for p in state:
                led = profile_last.get(p["linkedin_url"])
                if led:
                    p["last_engaged_date"] = led.isoformat()
                else:
                    p["last_engaged_date"] = (week_start - timedelta(days=7)).isoformat()
            
            week_end = week_start + timedelta(days=6)
            for pid in profile_max_gap.keys():
                led = profile_last.get(pid)
                if led:
                    current_gap = (week_start - led).days
                    if current_gap > 0:
                        profile_max_gap[pid] = max(profile_max_gap.get(pid, 0), current_gap)
            
            profile_last = simulate_week(
                state,
                failure_rate=failure_rate,
                already_reacted_rate=already_reacted_rate,
                no_posts_rate=no_posts_rate,
            )
            
            for pid in profile_max_gap.keys():
                led = profile_last.get(pid)
                if led:
                    final_gap = (week_end - led).days
                    if final_gap > 0:
                        profile_max_gap[pid] = max(profile_max_gap.get(pid, 0), final_gap)
                else:
                    final_gap = (week_end - (week_start - timedelta(days=7))).days
                    profile_max_gap[pid] = max(profile_max_gap.get(pid, 0), final_gap)

        for pid, gap in profile_max_gap.items():
            bucket = min(gap, 20)
            if bucket <= 7:
                coverage_buckets[7] += 1
            elif bucket <= 10:
                coverage_buckets[10] += 1
            elif bucket <= 12:
                coverage_buckets[12] += 1
            elif bucket <= 14:
                coverage_buckets[14] += 1
            else:
                coverage_buckets[16] += 1
        worst_gaps.append(max(profile_max_gap.values()) if profile_max_gap else 0)

    print("\n" + "=" * 60)
    print("SCHEDULER COVERAGE SIMULATION (Monte Carlo)")
    print("=" * 60)
    print(f"Weeks: {weeks}, Runs: {runs}")
    print(f"Failure rate: {failure_rate}, Already reacted: {already_reacted_rate}, No posts: {no_posts_rate}")
    print("-" * 60)
    total = runs * n_profiles
    for days in [7, 10, 12, 14, 16]:
        count = coverage_buckets.get(days, 0)
        pct = 100.0 * count / total if total else 0
        print(f"  Profiles engaged within {days} days: {pct:.1f}% ({count}/{total})")
    print(f"  Worst-case gap (max days any profile waited): avg={sum(worst_gaps)/len(worst_gaps):.1f}")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--weeks", type=int, default=12)
    parser.add_argument("--runs", type=int, default=50)
    parser.add_argument("--failure-rate", type=float, default=0.10)
    parser.add_argument("--already-reacted", type=float, default=0.05)
    parser.add_argument("--no-posts-rate", type=float, default=0.05)
    args = parser.parse_args()
    run_monte_carlo(
        weeks=args.weeks,
        runs=args.runs,
        failure_rate=args.failure_rate,
        already_reacted_rate=args.already_reacted,
        no_posts_rate=args.no_posts_rate,
    )


if __name__ == "__main__":
    main()
