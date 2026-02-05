from enum import Enum
from datetime import datetime, timedelta

class HealthEvent(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    RATE_LIMIT = "rate_limit"
    CAPTCHA = "captcha"
    SESSION_EXPIRED = "session_expired"

class HealthMonitor:
    def __init__(self):
        # score 0-100 (higher = healthier)
        self.score = 100
        self.last_change = datetime.now()
        self.pause_until = None

    def record(self, event: HealthEvent):
        """Adjust health score based on event and set pause windows when needed."""
        if event == HealthEvent.SUCCESS:
            self.score = min(100, self.score + 1)
        elif event == HealthEvent.FAILURE:
            self.score = max(0, self.score - 5)
        elif event == HealthEvent.RATE_LIMIT:
            self.score = max(0, self.score - 20)
        elif event == HealthEvent.CAPTCHA:
            self.score = max(0, self.score - 30)
        elif event == HealthEvent.SESSION_EXPIRED:
            self.score = max(0, self.score - 40)

        self.last_change = datetime.now()

        # Determine pause behavior based on score
        if self.score < 10:
            # Very low - require manual review; set an effectively infinite pause
            self.pause_until = datetime.now() + timedelta(days=3650)
        elif self.score < 30:
            # Pause for multiple days
            self.pause_until = datetime.now() + timedelta(days=3)
        elif self.score < 50:
            # Pause for 24 hours
            self.pause_until = datetime.now() + timedelta(days=1)
        else:
            self.pause_until = None

    def can_proceed(self) -> bool:
        if self.pause_until and datetime.now() < self.pause_until:
            return False
        return True

    def time_until_resume(self) -> timedelta:
        if not self.pause_until:
            return timedelta(0)
        return max(self.pause_until - datetime.now(), timedelta(0))
