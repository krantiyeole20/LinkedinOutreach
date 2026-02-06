"""
Stochastic scheduler: replaces rate_limiter.py.
Weekly plan generation, daily queue extraction, counter-based hard limits.
"""

import json
import random
from datetime import datetime, date, time, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytz
import structlog

from config.settings import settings
from src.weekly_plan import (
    WeeklyPlan,
    DailySlot,
    ScheduledEngagement,
)
from src.scorer import score_all_profiles, select_for_day, ScoredProfile
from src.timing import generate_daily_timestamps

logger = structlog.get_logger()


class Scheduler:
    """
    Replaces RateLimiter. Exposes same interface:
      - check_limits() -> Tuple[bool, str]
      - consume(amount=1)
      - status() -> dict

    Plus new capabilities:
      - generate_weekly_plan()
      - get_todays_queue() -> List[ScheduledEngagement]
      - mark_outcome(url, status)
    """

    def __init__(self):
        self.state_file = Path(
            getattr(settings, "SCHEDULE_STATE_FILE", "schedule_state.json")
        )
        if not self.state_file.is_absolute():
            base = Path(__file__).parent.parent
            self.state_file = base / self.state_file
        self.plan: Optional[WeeklyPlan] = None

        self.daily_count = 0
        self.weekly_count = 0
        self.hourly_count = 0
        # Make timezone-aware from the start
        tz = pytz.timezone(getattr(settings, "TIMEZONE", "America/New_York"))
        self.hourly_reset_time = datetime.now(tz)
        self.daily_reset_date = date.today()
        self.weekly_reset_date = date.today()

        self._load_state()

    def check_limits(self) -> Tuple[bool, str]:
        """Simple counter checks. Reset on boundary crossing."""
        self._maybe_reset_counters()

        hourly_limit = getattr(settings, "HOURLY_LIMIT", 5)
        daily_limit = getattr(settings, "DAILY_LIMIT", 20)
        weekly_limit = getattr(settings, "WEEKLY_LIMIT", 80)

        if self.hourly_count >= hourly_limit:
            return False, f"hourly_limit ({self.hourly_count}/{hourly_limit})"
        if self.daily_count >= daily_limit:
            return False, f"daily_limit ({self.daily_count}/{daily_limit})"
        if self.weekly_count >= weekly_limit:
            return False, f"weekly_limit ({self.weekly_count}/{weekly_limit})"
        return True, "ok"

    def consume(self, amount: int = 1):
        """Increment counters and persist state."""
        self.daily_count += amount
        self.weekly_count += amount
        self.hourly_count += amount
        self._save_state()
        logger.info(
            "scheduler_consumed",
            amount=amount,
            daily=self.daily_count,
            weekly=self.weekly_count,
            hourly=self.hourly_count,
        )

    def status(self) -> dict:
        hourly_limit = getattr(settings, "HOURLY_LIMIT", 5)
        daily_limit = getattr(settings, "DAILY_LIMIT", 20)
        weekly_limit = getattr(settings, "WEEKLY_LIMIT", 80)
        return {
            "daily": {"used": self.daily_count, "limit": daily_limit},
            "weekly": {"used": self.weekly_count, "limit": weekly_limit},
            "hourly": {"used": self.hourly_count, "limit": hourly_limit},
            "plan_exists": self.plan is not None,
            "plan_week": self.plan.week_number if self.plan else None,
        }

    def generate_weekly_plan(self, state_data: List[dict]) -> WeeklyPlan:
        """
        Called once per week. Scores profiles, samples daily budgets,
        selects for each day, assigns Poisson timestamps, persists.
        """
        tz = pytz.timezone(getattr(settings, "TIMEZONE", "America/New_York"))
        now = datetime.now(tz)
        today = now.date()
        week_start = today - timedelta(days=today.weekday())
        week_number = today.isocalendar()[1]

        scored = score_all_profiles(state_data, now)
        if not scored:
            logger.warning("no_profiles_to_score")
            return self._empty_plan(week_start, week_number)

        budgets = self._sample_daily_budgets()
        if len(budgets) != 7:
            logger.warning("invalid_budget_count", count=len(budgets))
            budgets = [12] * 7

        days: Dict[str, DailySlot] = {}
        yesterday_urls: set = set()

        for day_offset in range(7):
            slot_date = week_start + timedelta(days=day_offset)
            date_str = slot_date.isoformat()
            budget = budgets[day_offset] if day_offset < len(budgets) else 12

            selected = select_for_day(scored, budget, yesterday_urls)
            yesterday_urls = {p.linkedin_url for p in selected}

            timestamps = generate_daily_timestamps(len(selected))
            engagements = []
            for i, profile in enumerate(selected):
                ts = timestamps[i] if i < len(timestamps) else time(10, 0)
                engagements.append(
                    ScheduledEngagement(
                        linkedin_url=profile.linkedin_url,
                        name=profile.name,
                        scheduled_time=ts,
                        priority_score=profile.priority_score,
                        days_since_last_like=profile.days_since_last_like,
                        forced=profile.forced,
                        status="pending",
                    )
                )

            is_burst = (
                budget >= getattr(settings, "DAILY_BUDGET_MAX", 20) - 2
            )
            days[date_str] = DailySlot(
                date=slot_date,
                budget=budget,
                engagements=engagements,
                completed=0,
                is_burst_day=is_burst,
            )

        total_budget = sum(budgets)
        self.plan = WeeklyPlan(
            week_start=week_start,
            week_number=week_number,
            total_budget=total_budget,
            days=days,
            created_at=now,
        )
        self._save_state()
        logger.info(
            "weekly_plan_generated",
            week_number=week_number,
            total_budget=total_budget,
            days_planned=len(days),
        )
        return self.plan

    def get_todays_queue(self) -> List[ScheduledEngagement]:
        """
        Load plan, extract today's DailySlot, return pending engagements
        sorted by scheduled_time. Auto-generates if plan missing or stale.
        """
        today_str = date.today().isoformat()
        need_generate = False

        if self.plan is None:
            need_generate = True
            logger.info("no_plan_loaded_will_generate")
        else:
            plan_week = date.today().isocalendar()[1]
            if self.plan.week_number != plan_week:
                need_generate = True
                logger.info(
                    "plan_stale",
                    plan_week=self.plan.week_number,
                    current_week=plan_week,
                )
            elif today_str not in self.plan.days:
                need_generate = True
                logger.info("today_not_in_plan", today=today_str)

        if need_generate:
            try:
                client = self._get_sheets_client()
                client.initialize_state_tracker()
                state_data = client.get_state_tracker_data()
                profiles = client.get_all_profiles()
                profile_names = {p["linkedin_url"]: p.get("name", "") for p in profiles}
                for row in state_data:
                    url = row.get("linkedin_url")
                    if url and "name" not in row:
                        row["name"] = profile_names.get(url, "")
                self.generate_weekly_plan(state_data)
            except Exception as e:
                logger.error("failed_to_generate_plan", error=str(e))
                return []

        if self.plan is None:
            return []

        slot = self.plan.get_today()
        if slot is None:
            return []

        pending = [
            e for e in slot.engagements
            if e.status == "pending"
        ]
        pending.sort(key=lambda e: e.scheduled_time)
        return pending

    def mark_outcome(self, linkedin_url: str, outcome: str):
        """
        Update a ScheduledEngagement's status in the persisted plan.
        Outcomes: done, skipped, failed, already_reacted, no_posts
        """
        if self.plan is None:
            return
        today_str = date.today().isoformat()
        slot = self.plan.days.get(today_str)
        if slot is None:
            return
        for e in slot.engagements:
            if e.linkedin_url == linkedin_url and e.status == "pending":
                e.status = outcome
                if outcome == "done":
                    slot.completed += 1
                self._save_state()
                logger.info("outcome_marked", url=linkedin_url, outcome=outcome)
                return
        logger.debug("engagement_not_found_for_outcome", url=linkedin_url)

    def _maybe_reset_counters(self):
        """Reset hourly/daily/weekly on boundary crossing."""
        tz = pytz.timezone(getattr(settings, "TIMEZONE", "America/New_York"))
        now = datetime.now(tz)
        today = now.date()

        if now - self.hourly_reset_time >= timedelta(hours=1):
            self.hourly_count = 0
            self.hourly_reset_time = now
            logger.debug("hourly_counter_reset")

        if today > self.daily_reset_date:
            self.daily_count = 0
            self.daily_reset_date = today
            logger.info("daily_counter_reset")

        if today.weekday() == 0 and today > self.weekly_reset_date:
            self.weekly_count = 0
            self.weekly_reset_date = today
            logger.info("weekly_counter_reset")

    def _sample_daily_budgets(self) -> List[int]:
        """Sample 7 values from TruncatedNormal, adjust to sum to target."""
        mean = getattr(settings, "DAILY_BUDGET_MEAN", 12)
        std = getattr(settings, "DAILY_BUDGET_STD", 4)
        lo = getattr(settings, "DAILY_BUDGET_MIN", 5)
        hi = getattr(settings, "DAILY_BUDGET_MAX", 20)
        target = getattr(settings, "WEEKLY_BUDGET_TARGET", 80)
        burst_prob = getattr(settings, "BURST_DAY_PROBABILITY", 0.15)
        burst_min = getattr(settings, "BURST_DAY_EXTRA_MIN", 3)
        burst_max = getattr(settings, "BURST_DAY_EXTRA_MAX", 5)

        budgets = []
        for _ in range(7):
            v = random.gauss(mean, std)
            v = max(lo, min(hi, int(round(v))))
            budgets.append(v)

        total = sum(budgets)
        if total > target:
            scale = target / total
            budgets = [max(lo, min(hi, int(round(b * scale)))) for b in budgets]
        elif total < 70:
            scale = min(target, 70) / max(total, 1)
            budgets = [max(lo, min(hi, int(round(b * scale)))) for b in budgets]

        total = sum(budgets)
        diff = target - total
        indices = list(range(7))
        random.shuffle(indices)
        for i in indices:
            if diff == 0:
                break
            old = budgets[i]
            new = old + (1 if diff > 0 else -1)
            new = max(lo, min(hi, new))
            budgets[i] = new
            diff -= new - old

        if random.random() < burst_prob and 7 > 0:
            burst_idx = random.randint(0, 6)
            extra = random.randint(burst_min, burst_max)
            budgets[burst_idx] = min(hi, budgets[burst_idx] + extra)
        if random.random() < burst_prob and 7 > 0:
            light_idx = random.randint(0, 6)
            extra = random.randint(burst_min, burst_max)
            budgets[light_idx] = max(lo, budgets[light_idx] - extra)

        return budgets[:7]

    def _get_sheets_client(self):
        from src.sheets_client import get_sheets_client
        return get_sheets_client()

    def _load_state(self):
        """Load plan and counters from schedule_state.json."""
        if not self.state_file.exists():
            logger.debug("no_schedule_state_file")
            return
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning("schedule_state_load_failed", error=str(e))
            return

        counters = data.get("counters", {})
        self.daily_count = int(counters.get("daily_count", 0))
        self.weekly_count = int(counters.get("weekly_count", 0))
        self.hourly_count = int(counters.get("hourly_count", 0))
        try:
            hr = counters.get("hourly_reset_time")
            if hr:
                dt = datetime.fromisoformat(hr)
                # Ensure timezone-aware
                if dt.tzinfo is None:
                    tz = pytz.timezone(getattr(settings, "TIMEZONE", "America/New_York"))
                    dt = tz.localize(dt)
                self.hourly_reset_time = dt
        except (ValueError, TypeError):
            pass
        try:
            dd = counters.get("daily_reset_date")
            if dd:
                self.daily_reset_date = datetime.fromisoformat(dd).date()
        except (ValueError, TypeError):
            pass
        try:
            wd = counters.get("weekly_reset_date")
            if wd:
                self.weekly_reset_date = datetime.fromisoformat(wd).date()
        except (ValueError, TypeError):
            pass

        plan_data = data.get("plan")
        if plan_data:
            try:
                self.plan = WeeklyPlan.from_dict(plan_data)
            except Exception as e:
                logger.warning("plan_load_failed", error=str(e))

    def _save_state(self):
        """Persist plan and counters to schedule_state.json."""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            state = {
                "counters": {
                    "daily_count": self.daily_count,
                    "weekly_count": self.weekly_count,
                    "hourly_count": self.hourly_count,
                    "hourly_reset_time": self.hourly_reset_time.isoformat(),
                    "daily_reset_date": self.daily_reset_date.isoformat(),
                    "weekly_reset_date": self.weekly_reset_date.isoformat(),
                },
                "saved_at": datetime.now().isoformat(),
            }
            if self.plan:
                state["plan"] = self.plan.to_dict()
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except (IOError, OSError) as e:
            logger.error("schedule_state_save_failed", error=str(e))

    def _empty_plan(self, week_start: date, week_number: int) -> WeeklyPlan:
        self.plan = WeeklyPlan(
            week_start=week_start,
            week_number=week_number,
            total_budget=0,
            days={},
            created_at=datetime.now(),
        )
        return self.plan
