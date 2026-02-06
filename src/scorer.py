"""
Coverage-first priority scoring with weighted random sampling.
Replaces src/priority.py.
"""

import random
from datetime import datetime, date
from typing import List, Set, Optional
from dataclasses import dataclass

import structlog

from config.settings import settings

logger = structlog.get_logger()


@dataclass
class ScoredProfile:
    linkedin_url: str
    name: str
    priority_score: float
    days_since_last_like: float
    forced: bool = False


def calculate_priority(user_state: dict, current_time: datetime) -> float:
    """
    Coverage-first priority. No recency bonus.
    Score range: [0.0, 17.0]
      base: min(days_since * 0.8, 12.0)
      jitter: uniform(0.0, 5.0)
    """
    try:
        today = current_time.date() if hasattr(current_time, "date") else date.today()
        last_engaged_str = user_state.get("last_engaged_date") or user_state.get("last_engaged")
        if last_engaged_str:
            try:
                if isinstance(last_engaged_str, str):
                    last_engaged = datetime.fromisoformat(
                        last_engaged_str.replace("Z", "+00:00")
                    ).date()
                else:
                    last_engaged = last_engaged_str
                days_since = (today - last_engaged).days
            except (ValueError, TypeError) as e:
                logger.debug("invalid_last_engaged", value=last_engaged_str, error=str(e))
                days_since = 999
        else:
            days_since = 999

        weight = getattr(
            settings,
            "PRIORITY_DAYS_WEIGHT",
            0.8,
        )
        cap = getattr(settings, "PRIORITY_DAYS_CAP", 12.0)
        jitter_max = getattr(settings, "PRIORITY_JITTER_MAX", 5.0)

        base = min(days_since * weight, cap)
        jitter = random.uniform(0.0, jitter_max)
        return base + jitter
    except Exception as e:
        logger.warning("priority_calculation_error", error=str(e))
        return 0.0


def score_all_profiles(
    state_data: List[dict],
    current_time: Optional[datetime] = None,
) -> List[ScoredProfile]:
    """Score and return all active profiles, sorted descending by score."""
    if current_time is None:
        current_time = datetime.now()
    scored = []
    for profile in state_data:
        try:
            if str(profile.get("status", "active")).lower() != "active":
                continue
            url = profile.get("linkedin_url")
            if not url:
                continue
            score = calculate_priority(profile, current_time)
            today = current_time.date()
            last_engaged_str = profile.get("last_engaged_date") or profile.get("last_engaged")
            if last_engaged_str:
                try:
                    if isinstance(last_engaged_str, str):
                        last_engaged = datetime.fromisoformat(
                            last_engaged_str.replace("Z", "+00:00")
                        ).date()
                    else:
                        last_engaged = last_engaged_str
                    days_since = (today - last_engaged).days
                except (ValueError, TypeError):
                    days_since = 999
            else:
                days_since = 999

            force_threshold = getattr(
                settings,
                "FORCE_INCLUDE_DAYS_THRESHOLD",
                12,
            )
            forced = days_since > force_threshold

            scored.append(
                ScoredProfile(
                    linkedin_url=url,
                    name=str(profile.get("name", "")),
                    priority_score=score,
                    days_since_last_like=float(days_since),
                    forced=forced,
                )
            )
        except Exception as e:
            logger.warning(
                "failed_to_score_profile",
                profile=profile.get("linkedin_url", "?"),
                error=str(e),
            )
    scored.sort(key=lambda p: p.priority_score, reverse=True)
    return scored


def select_for_day(
    scored_profiles: List[ScoredProfile],
    budget: int,
    yesterday_urls: Set[str],
) -> List[ScoredProfile]:
    """
    1. Remove anyone liked yesterday
    2. Force-include profiles with days_since > 12 (up to 5)
    3. Build pool of top 2*budget profiles
    4. Weighted random sample from pool to fill remaining budget
    5. Return selected profiles (unordered)
    """
    if budget <= 0:
        return []

    force_max = getattr(settings, "FORCE_INCLUDE_MAX_PER_DAY", 5)
    pool_mult = getattr(settings, "SELECTION_POOL_MULTIPLIER", 2)
    pool_size = min(len(scored_profiles), budget * pool_mult)

    eligible = [p for p in scored_profiles if p.linkedin_url not in yesterday_urls]
    if not eligible:
        logger.warning("no_eligible_profiles_after_yesterday_filter")
        return []

    pool = eligible[:pool_size]
    if not pool:
        return []

    forced = [p for p in pool if p.forced][:force_max]
    forced_urls = {p.linkedin_url for p in forced}
    remaining_pool = [p for p in pool if p.linkedin_url not in forced_urls]

    selected = list(forced)
    slots_left = budget - len(selected)

    if slots_left <= 0:
        return selected[:budget]

    if not remaining_pool:
        return selected[:budget]

    weights = [max(0.01, p.priority_score) for p in remaining_pool]
    total_weight = sum(weights)
    if total_weight <= 0:
        total_weight = 1.0
    probs = [w / total_weight for w in weights]

    try:
        indices = random.choices(
            range(len(remaining_pool)),
            weights=probs,
            k=min(slots_left, len(remaining_pool)),
        )
        sampled = [remaining_pool[i] for i in indices]
        seen = set()
        unique_sampled = []
        for p in sampled:
            if p.linkedin_url not in seen:
                seen.add(p.linkedin_url)
                unique_sampled.append(p)
            if len(unique_sampled) >= slots_left:
                break
        selected.extend(unique_sampled[:slots_left])
    except Exception as e:
        logger.warning("weighted_sample_failed", error=str(e))
        selected.extend(remaining_pool[:slots_left])

    return selected[:budget]
