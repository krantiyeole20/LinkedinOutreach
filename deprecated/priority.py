"""
Deprecated: Replaced by src/scorer.py
Kept for rollback reference.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from dataclasses import dataclass
import random

@dataclass
class ProfilePriority:
    linkedin_url: str
    name: str
    priority_score: float
    days_since_engagement: int
    consecutive_skips: int
    last_post_days: int


def calculate_priority_score(
    days_since_last_engagement: int,
    consecutive_skips: int,
    last_post_days: int,
    total_engagement_count: int
) -> float:
    time_score = min(days_since_last_engagement * 10, 100)
    skip_score = min(consecutive_skips * 5, 50)

    if last_post_days <= 1:
        recency_bonus = 15
    elif last_post_days <= 3:
        recency_bonus = 10
    elif last_post_days <= 7:
        recency_bonus = 5
    else:
        recency_bonus = 0

    engagement_penalty = total_engagement_count * 0.5

    base_score = time_score + skip_score + recency_bonus - engagement_penalty
    randomization = random.uniform(-10, 10)

    return max(0, base_score + randomization)


def rank_profiles(profiles: List[dict]) -> List[ProfilePriority]:
    today = datetime.now().date()
    ranked = []

    for profile in profiles:
        if profile.get("status") != "active":
            continue

        last_engaged_str = profile.get("last_engaged_date", "")
        if last_engaged_str:
            try:
                last_engaged = datetime.fromisoformat(last_engaged_str).date()
                days_since = (today - last_engaged).days
            except (ValueError, TypeError):
                days_since = 999
        else:
            days_since = 999

        last_post_str = profile.get("last_post_date", "")
        if last_post_str:
            try:
                last_post = datetime.fromisoformat(last_post_str).date()
                post_days = (today - last_post).days
            except (ValueError, TypeError):
                post_days = 30
        else:
            post_days = 30

        consecutive_skips = int(profile.get("consecutive_skips") or 0)
        engagement_count = int(profile.get("engagement_count") or 0)

        score = calculate_priority_score(
            days_since_last_engagement=days_since,
            consecutive_skips=consecutive_skips,
            last_post_days=post_days,
            total_engagement_count=engagement_count
        )

        ranked.append(ProfilePriority(
            linkedin_url=profile["linkedin_url"],
            name=profile.get("name", ""),
            priority_score=score,
            days_since_engagement=days_since,
            consecutive_skips=consecutive_skips,
            last_post_days=post_days
        ))

    ranked.sort(key=lambda x: x.priority_score, reverse=True)
    return ranked


def select_daily_queue(
    ranked_profiles: List[ProfilePriority],
    limit: int = 20
) -> List[ProfilePriority]:
    selected = ranked_profiles[:limit]
    random.shuffle(selected)
    return selected
