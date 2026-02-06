"""
Priority score distribution analysis and forced-inclusion validation.
Runnable standalone: python -m tests.test_scorer_sim
"""

import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Ensure project root on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scorer import (
    calculate_priority,
    score_all_profiles,
    select_for_day,
    ScoredProfile,
)


def make_synthetic_profiles(n: int = 100) -> list:
    """Create profiles with varied days_since_last_like."""
    today = datetime.now().date()
    profiles = []
    for i in range(n):
        days_since = (i % 15) + (i // 15) * 3
        last_engaged = today - timedelta(days=days_since)
        profiles.append({
            "linkedin_url": f"https://linkedin.com/in/user{i}",
            "name": f"User {i}",
            "last_engaged_date": last_engaged.isoformat(),
            "status": "active",
            "consecutive_skips": 0,
            "engagement_count": i // 10,
        })
    return profiles


def run_scorer_sim():
    """Run priority score analysis over many rolls."""
    profiles = make_synthetic_profiles(100)
    n_runs = 1000
    budget = 20
    selection_counts = defaultdict(int)

    for _ in range(n_runs):
        scored = score_all_profiles(profiles)
        yesterday_urls = set()
        selected = select_for_day(scored, budget, yesterday_urls)
        for p in selected:
            selection_counts[p.linkedin_url] += 1

    print("\n" + "=" * 60)
    print("SCORER SIMULATION: Selection frequency per profile")
    print("=" * 60)
    sorted_urls = sorted(
        selection_counts.keys(),
        key=lambda u: int(u.split("user")[-1].rstrip("/")),
    )
    for url in sorted_urls[:30]:
        idx = url.split("user")[-1].rstrip("/")
        print(f"  Profile {idx:>3}: selected {selection_counts[url]:>4} / {n_runs}")
    if len(sorted_urls) > 30:
        print(f"  ... and {len(sorted_urls) - 30} more")
    print("=" * 60)

    days_buckets = defaultdict(list)
    for p in profiles:
        last = p.get("last_engaged_date", "")
        if last:
            try:
                ld = datetime.fromisoformat(last).date()
                days = (datetime.now().date() - ld).days
            except (ValueError, TypeError):
                days = 0
        else:
            days = 999
        bucket = min(days // 3, 5)
        days_buckets[bucket].append(p["linkedin_url"])

    print("\nForced-inclusion check (days_since > 12):")
    forced_candidates = [p for p in profiles if p.get("last_engaged_date")]
    forced_count = 0
    for p in forced_candidates:
        try:
            ld = datetime.fromisoformat(p["last_engaged_date"]).date()
            if (datetime.now().date() - ld).days > 12:
                forced_count += 1
        except (ValueError, TypeError):
            pass
    print(f"  Profiles with days_since > 12: {forced_count}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    run_scorer_sim()
