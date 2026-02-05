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
    LOG_FILE = BASE_DIR / "logs" / "engagement.log"
    
    GOOGLE_CREDENTIALS_FILE = BASE_DIR / "config" / "credentials.json"
    INPUT_SHEET_NAME = "LinkedIn_Profiles_Input"
    LOG_SHEET_NAME = "LinkedIn_Engagement_Log"
    STATE_TRACKER_SHEET_NAME = "LinkedIn_State_Tracker"
    
    HEADLESS = True
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