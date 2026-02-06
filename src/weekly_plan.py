"""
Data models for stochastic scheduler: WeeklyPlan, DailySlot, ScheduledEngagement.
"""

from dataclasses import dataclass, field
from datetime import date, time, datetime
from typing import Dict, List, Optional
import json

import structlog

logger = structlog.get_logger()


@dataclass
class ScheduledEngagement:
    linkedin_url: str
    name: str
    scheduled_time: time
    priority_score: float
    days_since_last_like: float
    forced: bool
    status: str = "pending"

    def to_dict(self) -> dict:
        return {
            "linkedin_url": self.linkedin_url,
            "name": self.name,
            "scheduled_time": self._time_to_str(self.scheduled_time),
            "priority_score": self.priority_score,
            "days_since_last_like": self.days_since_last_like,
            "forced": self.forced,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduledEngagement":
        return cls(
            linkedin_url=data.get("linkedin_url", ""),
            name=data.get("name", ""),
            scheduled_time=cls._str_to_time(data.get("scheduled_time", "09:00")),
            priority_score=float(data.get("priority_score", 0)),
            days_since_last_like=float(data.get("days_since_last_like", 0)),
            forced=bool(data.get("forced", False)),
            status=str(data.get("status", "pending")),
        )

    @staticmethod
    def _time_to_str(t: time) -> str:
        return t.strftime("%H:%M")

    @staticmethod
    def _str_to_time(s: str) -> time:
        try:
            parts = str(s).split(":")
            return time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
        except (ValueError, IndexError) as e:
            logger.warning("invalid_time_string", value=s, error=str(e))
            return time(9, 0)


@dataclass
class DailySlot:
    date: date
    budget: int
    engagements: List[ScheduledEngagement] = field(default_factory=list)
    completed: int = 0
    is_burst_day: bool = False

    def to_dict(self) -> dict:
        return {
            "budget": self.budget,
            "is_burst_day": self.is_burst_day,
            "completed": self.completed,
            "engagements": [e.to_dict() for e in self.engagements],
        }

    @classmethod
    def from_dict(cls, date_str: str, data: dict) -> "DailySlot":
        try:
            slot_date = datetime.fromisoformat(date_str).date()
        except (ValueError, TypeError) as e:
            logger.warning("invalid_date_string", value=date_str, error=str(e))
            slot_date = date.today()
        engagements = [
            ScheduledEngagement.from_dict(e)
            for e in data.get("engagements", [])
        ]
        return cls(
            date=slot_date,
            budget=int(data.get("budget", 0)),
            engagements=engagements,
            completed=int(data.get("completed", 0)),
            is_burst_day=bool(data.get("is_burst_day", False)),
        )


@dataclass
class WeeklyPlan:
    week_start: date
    week_number: int
    total_budget: int
    days: Dict[str, DailySlot] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "week_start": self.week_start.isoformat(),
            "week_number": self.week_number,
            "total_budget": self.total_budget,
            "created_at": self.created_at.isoformat(),
            "days": {
                k: v.to_dict() for k, v in self.days.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WeeklyPlan":
        try:
            week_start = datetime.fromisoformat(
                data.get("week_start", "")
            ).date()
        except (ValueError, TypeError):
            week_start = date.today()
        week_number = int(data.get("week_number", 0))
        total_budget = int(data.get("total_budget", 0))
        try:
            created_at = datetime.fromisoformat(data.get("created_at", ""))
        except (ValueError, TypeError):
            created_at = datetime.now()
        days = {}
        for date_str, slot_data in data.get("days", {}).items():
            try:
                days[date_str] = DailySlot.from_dict(date_str, slot_data)
            except Exception as e:
                logger.warning(
                    "failed_to_parse_daily_slot",
                    date=date_str,
                    error=str(e),
                )
        return cls(
            week_start=week_start,
            week_number=week_number,
            total_budget=total_budget,
            days=days,
            created_at=created_at,
        )

    def get_today(self) -> Optional[DailySlot]:
        today_str = date.today().isoformat()
        return self.days.get(today_str)

    def total_completed(self) -> int:
        return sum(slot.completed for slot in self.days.values())
