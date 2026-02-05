import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple
import pytz

import structlog

from config.settings import settings

logger = structlog.get_logger()

class TokenBucket:
    def __init__(self, capacity: int, refill_amount: int, refill_interval: timedelta):
        self.capacity = capacity
        self.refill_amount = refill_amount
        self.refill_interval = refill_interval
        self.tokens = capacity
        self.last_refill = datetime.now(pytz.timezone(settings.TIMEZONE))
    
    def refill(self, current_time: datetime):
        raise NotImplementedError
    
    def consume(self, amount: int = 1) -> bool:
        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False
    
    def to_dict(self) -> dict:
        return {
            "tokens": self.tokens,
            "last_refill": self.last_refill.isoformat()
        }
    
    def from_dict(self, data: dict):
        self.tokens = data.get("tokens", self.capacity)
        self.last_refill = datetime.fromisoformat(data["last_refill"])

class DailyBucket(TokenBucket):
    def __init__(self):
        super().__init__(
            capacity=settings.DAILY_LIMIT,
            refill_amount=settings.DAILY_LIMIT,
            refill_interval=timedelta(days=1)
        )
    
    def refill(self, current_time: datetime):
        tz = pytz.timezone(settings.TIMEZONE)
        current_date = current_time.astimezone(tz).date()
        last_refill_date = self.last_refill.astimezone(tz).date()
        
        if current_date > last_refill_date:
            self.tokens = self.capacity
            self.last_refill = current_time
            logger.info("daily_bucket_refilled", tokens=self.tokens)

class WeeklyBucket(TokenBucket):
    def __init__(self):
        super().__init__(
            capacity=settings.WEEKLY_LIMIT,
            refill_amount=settings.WEEKLY_LIMIT,
            refill_interval=timedelta(weeks=1)
        )
    
    def refill(self, current_time: datetime):
        tz = pytz.timezone(settings.TIMEZONE)
        current_dt = current_time.astimezone(tz)
        last_refill_dt = self.last_refill.astimezone(tz)
        
        current_week = current_dt.isocalendar()[1]
        last_refill_week = last_refill_dt.isocalendar()[1]
        
        is_monday = current_dt.weekday() == 0
        different_week = current_week != last_refill_week or current_dt.year != last_refill_dt.year
        
        if is_monday and different_week:
            self.tokens = self.capacity
            self.last_refill = current_time
            logger.info("weekly_bucket_refilled", tokens=self.tokens)

class HourlyBucket(TokenBucket):
    def __init__(self):
        super().__init__(
            capacity=settings.HOURLY_LIMIT,
            refill_amount=settings.HOURLLY_LIMIT if hasattr(settings, 'HOURLLY_LIMIT') else settings.HOURLY_LIMIT,
            refill_interval=timedelta(hours=1)
        )
    
    def refill(self, current_time: datetime):
        elapsed = current_time - self.last_refill
        
        if elapsed >= self.refill_interval:
            self.tokens = self.capacity
            self.last_refill = current_time
            logger.debug("hourly_bucket_refilled", tokens=self.tokens)

class RateLimiter:
    def __init__(self):
        self.daily = DailyBucket()
        self.weekly = WeeklyBucket()
        self.hourly = HourlyBucket()
        self.state_file = settings.RATE_LIMIT_STATE_FILE
        
        self._load_state()
    
    def _load_state(self):
        if self.state_file.exists():
            try:
                with open(self.state_file, "r") as f:
                    state = json.load(f)
                
                if "daily" in state:
                    self.daily.from_dict(state["daily"])
                if "weekly" in state:
                    self.weekly.from_dict(state["weekly"])
                if "hourly" in state:
                    self.hourly.from_dict(state["hourly"])
                
                logger.info("rate_limit_state_loaded")
            except Exception as e:
                logger.warning("rate_limit_state_load_failed", error=str(e))
    
    def _save_state(self):
        state = {
            "daily": self.daily.to_dict(),
            "weekly": self.weekly.to_dict(),
            "hourly": self.hourly.to_dict(),
            "saved_at": datetime.now().isoformat()
        }
        
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)
    
    def check_limits(self) -> Tuple[bool, str]:
        current_time = datetime.now(pytz.timezone(settings.TIMEZONE))
        
        self.daily.refill(current_time)
        self.weekly.refill(current_time)
        self.hourly.refill(current_time)
        
        if self.hourly.tokens <= 0:
            return False, f"hourly_limit (0/{settings.HOURLY_LIMIT})"
        
        if self.daily.tokens <= 0:
            return False, f"daily_limit (0/{settings.DAILY_LIMIT})"
        
        if self.weekly.tokens <= 0:
            return False, f"weekly_limit (0/{settings.WEEKLY_LIMIT})"
        
        return True, "ok"
    
    def consume(self, amount: int = 1):
        self.daily.consume(amount)
        self.weekly.consume(amount)
        self.hourly.consume(amount)
        
        self._save_state()
        
        logger.info("tokens_consumed", 
                   daily=f"{self.daily.tokens}/{settings.DAILY_LIMIT}",
                   weekly=f"{self.weekly.tokens}/{settings.WEEKLY_LIMIT}",
                   hourly=f"{self.hourly.tokens}/{settings.HOURLY_LIMIT}")
    
    def status(self) -> dict:
        return {
            "daily": {"remaining": self.daily.tokens, "limit": settings.DAILY_LIMIT},
            "weekly": {"remaining": self.weekly.tokens, "limit": settings.WEEKLY_LIMIT},
            "hourly": {"remaining": self.hourly.tokens, "limit": settings.HOURLY_LIMIT}
        }


def status():
    limiter = RateLimiter()
    s = limiter.status()
    print("\n" + "="*40)
    print("RATE LIMIT STATUS")
    print("="*40)
    print(f"Hourly:  {s['hourly']['remaining']}/{s['hourly']['limit']}")
    print(f"Daily:   {s['daily']['remaining']}/{s['daily']['limit']}")
    print(f"Weekly:  {s['weekly']['remaining']}/{s['weekly']['limit']}")
    print("="*40 + "\n")


def test_limits():
    limiter = RateLimiter()
    can_proceed, info = limiter.check_limits()
    
    if can_proceed:
        print("All limits OK - ready to engage")
    else:
        print(f"Limit reached: {info}")
