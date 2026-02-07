import os
from pathlib import Path
from datetime import time

BASE_DIR = Path(__file__).parent.parent

class Settings:
    DAILY_LIMIT = 20
    WEEKLY_LIMIT = 80
    HOURLY_LIMIT = 5
    
    OPERATING_START = time(9, 0)
    OPERATING_END = time(18, 0)
    TIMEZONE = "America/New_York"
    
    MIN_DELAY_SECONDS = 180
    MAX_DELAY_SECONDS = 480
    NOISE_ACTION_PROBABILITY = 0.10
    
    COOKIES_FILE = BASE_DIR / "linkedin_cookies.json"
    RATE_LIMIT_STATE_FILE = BASE_DIR / "rate_limit_state.json"
    SCHEDULE_STATE_FILE = BASE_DIR / "schedule_state.json"
    LOG_FILE = BASE_DIR / "logs" / "engagement.log"
    
    # Session file logic - check root first, then submodule
    SESSION_FILE = BASE_DIR / "linkedin_session.json"
    if not SESSION_FILE.exists():
        SUBMODULE_SESSION = BASE_DIR / "linkedin_scraper" / "linkedin_session.json"
        if SUBMODULE_SESSION.exists():
            SESSION_FILE = SUBMODULE_SESSION

    # Stochastic Scheduler
    WEEKLY_BUDGET_TARGET = 80
    DAILY_BUDGET_MEAN = 12
    DAILY_BUDGET_STD = 4
    DAILY_BUDGET_MIN = 5
    DAILY_BUDGET_MAX = 20

    FORCE_INCLUDE_DAYS_THRESHOLD = 12
    FORCE_INCLUDE_MAX_PER_DAY = 5
    COVERAGE_GUARANTEE_DAYS = 14

    PRIORITY_DAYS_WEIGHT = 0.8
    PRIORITY_DAYS_CAP = 12.0
    PRIORITY_JITTER_MAX = 5.0
    SELECTION_POOL_MULTIPLIER = 2

    TIMING_RATE_MORNING_WARMUP = 0.6
    TIMING_RATE_MID_MORNING = 1.3
    TIMING_RATE_LUNCH_DIP = 0.8
    TIMING_RATE_AFTERNOON_PEAK = 1.2
    TIMING_RATE_AFTERNOON_WIND = 0.7
    TIMING_RATE_END_OF_DAY = 0.4
    TIMING_MIN_GAP_MINUTES = 3
    TIMING_JITTER_MINUTES = 5

    BURST_DAY_PROBABILITY = 0.15
    BURST_DAY_EXTRA_MIN = 3
    BURST_DAY_EXTRA_MAX = 5
    
    GOOGLE_CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"
    INPUT_SHEET_NAME = "LinkedIn_Profiles_Input"
    LOG_SHEET_NAME = "LinkedIn_Engagement_Log"
    STATE_TRACKER_SHEET_NAME = "LinkedIn_State_Tracker"
    
    HEADLESS = False
    VIEWPORT_WIDTH = 1920
    VIEWPORT_HEIGHT = 1080
    PAGE_TIMEOUT = 30000
    
    SENTENCE_TRANSFORMER_MODEL = "all-MiniLM-L6-v2"
    REACTION_CONFIDENCE_THRESHOLD = 0.5
    
    @classmethod
    def get_random_delay(cls):
        import random
        base = random.randint(cls.MIN_DELAY_SECONDS, cls.MAX_DELAY_SECONDS)
        jitter = random.gauss(0, 30)
        return max(60, int(base + jitter))

settings = Settings()