# LinkedIn Automation - Code Reference

All code snippets referenced in the Implementation Guide.

---

## Section 1.1: requirements.txt

```txt
playwright==1.40.0
google-auth==2.25.0
google-auth-oauthlib==1.2.0
google-api-python-client==2.108.0
gspread==5.12.0
sentence-transformers==2.2.2
python-dateutil==2.8.2
pytz==2023.3
pydantic==2.5.0
structlog==23.2.0
tenacity==8.2.3
```

---

## Section 2.1: setup_session.py

```python
import json
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

COOKIES_FILE = Path("linkedin_cookies.json")

async def setup_linkedin_session():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        await page.goto("https://www.linkedin.com/login")
        
        print("\n" + "="*50)
        print("MANUAL LOGIN REQUIRED")
        print("="*50)
        print("1. Log into LinkedIn in the browser window")
        print("2. Complete any 2FA/CAPTCHA if prompted")
        print("3. Wait until you see your LinkedIn feed")
        print("4. Press ENTER here when done")
        print("="*50 + "\n")
        
        input("Press ENTER after logging in...")
        
        cookies = await context.cookies()
        
        with open(COOKIES_FILE, "w") as f:
            json.dump(cookies, f, indent=2)
        
        print(f"\nCookies saved to {COOKIES_FILE}")
        print(f"Total cookies: {len(cookies)}")
        
        li_at = next((c for c in cookies if c["name"] == "li_at"), None)
        if li_at:
            print("Session cookie (li_at) found - setup successful")
        else:
            print("WARNING: li_at cookie not found - login may have failed")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(setup_linkedin_session())
```

---

## Section 3.1: config/settings.py

```python
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
```

---

## Section 3.2: src/post_fetcher.py

```python
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import dataclass
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

import structlog

logger = structlog.get_logger()

@dataclass
class PostData:
    post_id: str
    content: str
    timestamp: datetime
    author_name: str
    has_image: bool
    has_video: bool
    reaction_count: int
    comment_count: int

class PostFetcher:
    ACTIVITY_URL_TEMPLATE = "https://www.linkedin.com/in/{username}/recent-activity/all/"
    
    POST_CONTAINER_SELECTOR = "div.feed-shared-update-v2"
    POST_TEXT_SELECTOR = "div.feed-shared-update-v2__description"
    POST_TIME_SELECTOR = "span.feed-shared-actor__sub-description"
    REACTION_BUTTON_SELECTOR = "button.reactions-react-button"
    
    def __init__(self, page: Page):
        self.page = page
    
    async def fetch_recent_post(self, profile_url: str) -> Optional[PostData]:
        try:
            username = self._extract_username(profile_url)
            if not username:
                logger.error("invalid_profile_url", url=profile_url)
                return None
            
            activity_url = self.ACTIVITY_URL_TEMPLATE.format(username=username)
            
            await self.page.goto(activity_url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(2000)
            
            error_check = await self._check_for_errors()
            if error_check:
                logger.warning("profile_error", error=error_check, url=profile_url)
                return None
            
            await self._scroll_to_load_posts()
            
            posts = await self.page.query_selector_all(self.POST_CONTAINER_SELECTOR)
            
            if not posts:
                logger.info("no_posts_found", url=profile_url)
                return None
            
            first_post = posts[0]
            
            post_data = await self._extract_post_data(first_post, profile_url)
            
            return post_data
            
        except PlaywrightTimeout:
            logger.error("timeout_fetching_post", url=profile_url)
            return None
        except Exception as e:
            logger.error("fetch_post_error", url=profile_url, error=str(e))
            return None
    
    def _extract_username(self, profile_url: str) -> Optional[str]:
        patterns = [
            r"linkedin\.com/in/([^/\?]+)",
            r"linkedin\.com/pub/([^/\?]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, profile_url)
            if match:
                return match.group(1)
        return None
    
    async def _check_for_errors(self) -> Optional[str]:
        page_content = await self.page.content()
        
        if "This profile is not available" in page_content:
            return "profile_not_available"
        if "Page not found" in page_content:
            return "page_not_found"
        if "Sign in" in page_content and "Join now" in page_content:
            return "session_expired"
        if "/checkpoint/challenge" in self.page.url:
            return "captcha_challenge"
        
        return None
    
    async def _scroll_to_load_posts(self):
        await self.page.evaluate("window.scrollTo(0, 500)")
        await self.page.wait_for_timeout(1000)
    
    async def _extract_post_data(self, post_element, profile_url: str) -> PostData:
        post_id = await post_element.get_attribute("data-urn") or ""
        if ":" in post_id:
            post_id = post_id.split(":")[-1]
        
        content = ""
        text_element = await post_element.query_selector(self.POST_TEXT_SELECTOR)
        if text_element:
            content = await text_element.inner_text()
            content = content[:500]
        
        has_image = await post_element.query_selector("img.feed-shared-image") is not None
        has_video = await post_element.query_selector("video") is not None
        
        timestamp = datetime.now()
        time_element = await post_element.query_selector(self.POST_TIME_SELECTOR)
        if time_element:
            time_text = await time_element.inner_text()
            timestamp = self._parse_relative_time(time_text)
        
        return PostData(
            post_id=post_id,
            content=content,
            timestamp=timestamp,
            author_name=self._extract_username(profile_url) or "",
            has_image=has_image,
            has_video=has_video,
            reaction_count=0,
            comment_count=0
        )
    
    def _parse_relative_time(self, time_text: str) -> datetime:
        now = datetime.now()
        time_text = time_text.lower()
        
        if "now" in time_text or "just" in time_text:
            return now
        
        patterns = {
            r"(\d+)\s*m(?:in)?": lambda m: now - timedelta(minutes=int(m)),
            r"(\d+)\s*h(?:our)?": lambda m: now - timedelta(hours=int(m)),
            r"(\d+)\s*d(?:ay)?": lambda m: now - timedelta(days=int(m)),
            r"(\d+)\s*w(?:eek)?": lambda m: now - timedelta(weeks=int(m)),
            r"(\d+)\s*mo(?:nth)?": lambda m: now - timedelta(days=int(m)*30),
        }
        
        for pattern, calc in patterns.items():
            match = re.search(pattern, time_text)
            if match:
                return calc(int(match.group(1)))
        
        return now

    async def get_reaction_button_state(self, post_element) -> dict:
        button = await post_element.query_selector(self.REACTION_BUTTON_SELECTOR)
        if not button:
            return {"found": False, "already_reacted": False, "current_reaction": None}
        
        aria_pressed = await button.get_attribute("aria-pressed")
        aria_label = await button.get_attribute("aria-label") or ""
        
        already_reacted = aria_pressed == "true"
        current_reaction = None
        
        if already_reacted:
            for reaction in ["Like", "Celebrate", "Support", "Love", "Insightful", "Funny"]:
                if reaction.lower() in aria_label.lower():
                    current_reaction = reaction
                    break
        
        return {
            "found": True,
            "already_reacted": already_reacted,
            "current_reaction": current_reaction
        }
```

---

## Section 3.3: src/reaction_analyzer.py

```python
from sentence_transformers import SentenceTransformer, util
import numpy as np
from typing import Tuple
from enum import Enum

import structlog

logger = structlog.get_logger()

class ReactionType(Enum):
    LIKE = "Like"
    CELEBRATE = "Celebrate"
    SUPPORT = "Support"
    LOVE = "Love"
    INSIGHTFUL = "Insightful"
    FUNNY = "Funny"

REACTION_CATEGORIES = {
    ReactionType.CELEBRATE: [
        "congratulations on the new job",
        "excited to announce promotion",
        "achieved milestone reached goal",
        "celebrating success anniversary",
        "new role new position",
        "thrilled to share good news",
        "award recognition achievement",
        "graduation completed certification",
        "company milestone funding round"
    ],
    ReactionType.SUPPORT: [
        "going through difficult time",
        "facing challenges struggling",
        "layoff job search unemployment",
        "mental health awareness",
        "seeking advice need help",
        "dealing with setback failure",
        "support needed tough times",
        "grief loss mourning",
        "health issues recovery"
    ],
    ReactionType.LOVE: [
        "inspiring story motivation",
        "passion dedication commitment",
        "heartwarming touching story",
        "giving back charity volunteer",
        "family personal milestone",
        "grateful thankful appreciation",
        "beautiful moment captured",
        "love what I do passion"
    ],
    ReactionType.INSIGHTFUL: [
        "industry insights trends",
        "learned lesson experience",
        "data analysis research findings",
        "thought leadership opinion",
        "tips advice recommendations",
        "strategy framework methodology",
        "case study analysis",
        "market trends predictions",
        "technical deep dive explanation"
    ],
    ReactionType.FUNNY: [
        "funny story humor joke",
        "meme hilarious laughing",
        "workplace humor office jokes",
        "friday mood weekend vibes",
        "relatable content sarcasm",
        "plot twist unexpected ending",
        "tech humor developer jokes"
    ]
}

class ReactionAnalyzer:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        logger.info("loading_sentence_transformer", model=model_name)
        self.model = SentenceTransformer(model_name)
        self._build_category_embeddings()
    
    def _build_category_embeddings(self):
        self.category_embeddings = {}
        
        for reaction_type, phrases in REACTION_CATEGORIES.items():
            embeddings = self.model.encode(phrases, convert_to_tensor=True)
            self.category_embeddings[reaction_type] = embeddings
        
        logger.info("category_embeddings_built", categories=len(self.category_embeddings))
    
    def analyze(self, post_content: str, confidence_threshold: float = 0.5) -> Tuple[ReactionType, float]:
        if not post_content or len(post_content.strip()) < 10:
            logger.info("content_too_short_defaulting_to_like")
            return ReactionType.LIKE, 0.0
        
        post_embedding = self.model.encode(post_content, convert_to_tensor=True)
        
        best_reaction = ReactionType.LIKE
        best_score = 0.0
        
        scores = {}
        
        for reaction_type, category_embeddings in self.category_embeddings.items():
            similarities = util.cos_sim(post_embedding, category_embeddings)
            max_similarity = float(similarities.max())
            avg_similarity = float(similarities.mean())
            
            combined_score = 0.7 * max_similarity + 0.3 * avg_similarity
            scores[reaction_type.value] = round(combined_score, 3)
            
            if combined_score > best_score:
                best_score = combined_score
                best_reaction = reaction_type
        
        logger.debug("reaction_scores", scores=scores, selected=best_reaction.value)
        
        if best_score < confidence_threshold:
            logger.info("low_confidence_defaulting_to_like", 
                       best_score=best_score, threshold=confidence_threshold)
            return ReactionType.LIKE, best_score
        
        return best_reaction, best_score


_analyzer_instance = None

def get_analyzer() -> ReactionAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = ReactionAnalyzer()
    return _analyzer_instance

def test_analyzer():
    analyzer = get_analyzer()
    
    test_cases = [
        "Excited to announce I've just been promoted to Senior Manager!",
        "Going through a tough time after being laid off last week.",
        "Here are 5 tips for better productivity I learned this year.",
        "When you realize it's only Tuesday... #MondayMood",
        "Feeling grateful for this amazing team I get to work with.",
    ]
    
    print("\n" + "="*60)
    print("REACTION ANALYZER TEST")
    print("="*60)
    
    for content in test_cases:
        reaction, confidence = analyzer.analyze(content)
        print(f"\nContent: {content[:50]}...")
        print(f"Reaction: {reaction.value} (confidence: {confidence:.2f})")
    
    print("\n" + "="*60)
```

---

## Section 3.4: src/engagement.py

```python
import asyncio
import json
import random
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from playwright.async_api import async_playwright, Page, BrowserContext

import structlog

from config.settings import settings
from src.post_fetcher import PostFetcher, PostData
from src.reaction_analyzer import get_analyzer, ReactionType
from src.rate_limiter import RateLimiter

logger = structlog.get_logger()

@dataclass
class EngagementResult:
    success: bool
    profile_url: str
    action_type: Optional[str]
    post_id: Optional[str]
    post_content: Optional[str]
    error_code: Optional[str]
    error_message: Optional[str]
    timestamp: datetime

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "profile_url": self.profile_url,
            "action_type": self.action_type,
            "post_id": self.post_id,
            "post_content": self.post_content[:200] if self.post_content else None,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "timestamp": self.timestamp.isoformat()
        }

class LinkedInEngagement:
    REACTION_BUTTON_SELECTOR = "button.reactions-react-button"
    REACTION_PICKER_SELECTOR = "div.reactions-menu"
    
    REACTION_SELECTORS = {
        ReactionType.LIKE: "button[aria-label*='Like']",
        ReactionType.CELEBRATE: "button[aria-label*='Celebrate']",
        ReactionType.SUPPORT: "button[aria-label*='Support']",
        ReactionType.LOVE: "button[aria-label*='Love']",
        ReactionType.INSIGHTFUL: "button[aria-label*='Insightful']",
        ReactionType.FUNNY: "button[aria-label*='Funny']",
    }

    def __init__(self):
        self.rate_limiter = RateLimiter()
        self.analyzer = get_analyzer()
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def initialize(self):
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=settings.HEADLESS
        )
        
        self.context = await self.browser.new_context(
            viewport={
                "width": settings.VIEWPORT_WIDTH,
                "height": settings.VIEWPORT_HEIGHT
            },
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        
        await self._load_cookies()
        
        self.page = await self.context.new_page()
        self.page.set_default_timeout(settings.PAGE_TIMEOUT)

    async def _load_cookies(self):
        if not settings.COOKIES_FILE.exists():
            raise FileNotFoundError(f"Cookies file not found: {settings.COOKIES_FILE}")
        
        with open(settings.COOKIES_FILE, "r") as f:
            cookies = json.load(f)
        
        await self.context.add_cookies(cookies)
        logger.info("cookies_loaded", count=len(cookies))

    async def engage(self, profile_url: str, dry_run: bool = False) -> EngagementResult:
        log = logger.bind(profile_url=profile_url)
        
        try:
            can_proceed, limit_info = self.rate_limiter.check_limits()
            if not can_proceed:
                log.warning("rate_limit_exceeded", info=limit_info)
                return EngagementResult(
                    success=False,
                    profile_url=profile_url,
                    action_type=None,
                    post_id=None,
                    post_content=None,
                    error_code="rate_limit_exceeded",
                    error_message=f"Limit reached: {limit_info}",
                    timestamp=datetime.now()
                )
            
            post_fetcher = PostFetcher(self.page)
            post_data = await post_fetcher.fetch_recent_post(profile_url)
            
            if not post_data:
                log.info("no_recent_post")
                return EngagementResult(
                    success=False,
                    profile_url=profile_url,
                    action_type=None,
                    post_id=None,
                    post_content=None,
                    error_code="no_posts",
                    error_message="No recent posts found",
                    timestamp=datetime.now()
                )
            
            posts = await self.page.query_selector_all("div.feed-shared-update-v2")
            if not posts:
                return self._error_result(profile_url, "post_element_not_found", "Could not find post element")
            
            first_post = posts[0]
            reaction_state = await post_fetcher.get_reaction_button_state(first_post)
            
            if reaction_state.get("already_reacted"):
                log.info("already_reacted", current=reaction_state.get("current_reaction"))
                return EngagementResult(
                    success=False,
                    profile_url=profile_url,
                    action_type=None,
                    post_id=post_data.post_id,
                    post_content=post_data.content,
                    error_code="already_reacted",
                    error_message=f"Already reacted: {reaction_state.get('current_reaction')}",
                    timestamp=datetime.now()
                )
            
            reaction_type, confidence = self.analyzer.analyze(post_data.content)
            log.info("reaction_selected", reaction=reaction_type.value, confidence=confidence)
            
            if dry_run:
                log.info("dry_run_skip_click")
                return EngagementResult(
                    success=True,
                    profile_url=profile_url,
                    action_type=f"DRY_RUN_{reaction_type.value}",
                    post_id=post_data.post_id,
                    post_content=post_data.content,
                    error_code=None,
                    error_message=None,
                    timestamp=datetime.now()
                )
            
            await self._perform_reaction(first_post, reaction_type)
            
            self.rate_limiter.consume()
            
            log.info("engagement_success", reaction=reaction_type.value, post_id=post_data.post_id)
            
            return EngagementResult(
                success=True,
                profile_url=profile_url,
                action_type=reaction_type.value,
                post_id=post_data.post_id,
                post_content=post_data.content,
                error_code=None,
                error_message=None,
                timestamp=datetime.now()
            )
            
        except Exception as e:
            log.error("engagement_error", error=str(e))
            return self._error_result(profile_url, "unexpected_error", str(e))

    async def _perform_reaction(self, post_element, reaction_type: ReactionType):
        reaction_btn = await post_element.query_selector(self.REACTION_BUTTON_SELECTOR)
        if not reaction_btn:
            raise Exception("Reaction button not found")
        
        await self._human_like_move_to(reaction_btn)
        
        await reaction_btn.hover()
        await self.page.wait_for_timeout(random.randint(800, 1500))
        
        picker = await self.page.wait_for_selector(
            self.REACTION_PICKER_SELECTOR,
            timeout=5000
        )
        
        if reaction_type == ReactionType.LIKE:
            await reaction_btn.click()
        else:
            reaction_selector = self.REACTION_SELECTORS.get(reaction_type)
            specific_btn = await picker.query_selector(reaction_selector)
            
            if specific_btn:
                await self._human_like_move_to(specific_btn)
                await specific_btn.click()
            else:
                logger.warning("specific_reaction_not_found_using_like", requested=reaction_type.value)
                await reaction_btn.click()
        
        await self.page.wait_for_timeout(random.randint(500, 1000))

    async def _human_like_move_to(self, element):
        box = await element.bounding_box()
        if box:
            target_x = box["x"] + box["width"] / 2 + random.randint(-5, 5)
            target_y = box["y"] + box["height"] / 2 + random.randint(-3, 3)
            
            await self.page.mouse.move(target_x, target_y, steps=random.randint(10, 25))
            await self.page.wait_for_timeout(random.randint(100, 300))

    def _error_result(self, profile_url: str, code: str, message: str) -> EngagementResult:
        return EngagementResult(
            success=False,
            profile_url=profile_url,
            action_type=None,
            post_id=None,
            post_content=None,
            error_code=code,
            error_message=message,
            timestamp=datetime.now()
        )

    async def close(self):
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()


def test_cookies():
    if not settings.COOKIES_FILE.exists():
        print("FAILED: Cookies file not found")
        return
    
    with open(settings.COOKIES_FILE, "r") as f:
        cookies = json.load(f)
    
    li_at = next((c for c in cookies if c["name"] == "li_at"), None)
    
    if li_at:
        print("Cookies valid - li_at session cookie found")
    else:
        print("WARNING: li_at cookie not found - session may be invalid")
```

---

## Section 4.1: src/rate_limiter.py

```python
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
            refill_amount=settings.HOURLY_LIMIT,
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
```

---

## Section 5.1: Priority Algorithm

```python
from datetime import datetime, timedelta
from typing import List
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
    """
    Higher score = higher priority for engagement
    
    Weights:
    - days_since_last_engagement: 10 points per day (max 100)
    - consecutive_skips: 5 points per skip (max 50)
    - recency_bonus: 15 if posted in last 24h, 10 if last 3 days
    - engagement_penalty: -0.5 per previous engagement (avoid over-engaging)
    """
    
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
    """
    Input: List of profile dicts from State Tracker sheet
    Output: Sorted list of ProfilePriority objects (highest first)
    """
    today = datetime.now().date()
    ranked = []
    
    for profile in profiles:
        if profile.get("status") != "active":
            continue
        
        last_engaged_str = profile.get("last_engaged_date")
        if last_engaged_str:
            try:
                last_engaged = datetime.fromisoformat(last_engaged_str).date()
                days_since = (today - last_engaged).days
            except:
                days_since = 999
        else:
            days_since = 999
        
        last_post_str = profile.get("last_post_date")
        if last_post_str:
            try:
                last_post = datetime.fromisoformat(last_post_str).date()
                post_days = (today - last_post).days
            except:
                post_days = 30
        else:
            post_days = 30
        
        consecutive_skips = int(profile.get("consecutive_skips", 0))
        engagement_count = int(profile.get("engagement_count", 0))
        
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


def select_daily_queue(ranked_profiles: List[ProfilePriority], limit: int = 20) -> List[ProfilePriority]:
    """
    Select top profiles and shuffle for randomized order
    """
    selected = ranked_profiles[:limit]
    
    random.shuffle(selected)
    
    return selected
```

---

## Section 5.2: src/sheets_client.py

```python
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import List, Optional
import random

import structlog

from config.settings import settings

logger = structlog.get_logger()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

class SheetsClient:
    def __init__(self):
        self.credentials = Credentials.from_service_account_file(
            settings.GOOGLE_CREDENTIALS_FILE,
            scopes=SCOPES
        )
        self.client = gspread.authorize(self.credentials)
        
        self.input_sheet = None
        self.log_sheet = None
        self.state_sheet = None
    
    def connect(self):
        try:
            input_wb = self.client.open(settings.INPUT_SHEET_NAME)
            self.input_sheet = input_wb.sheet1
            
            log_wb = self.client.open(settings.LOG_SHEET_NAME)
            self.log_sheet = log_wb.sheet1
            
            state_wb = self.client.open(settings.STATE_TRACKER_SHEET_NAME)
            self.state_sheet = state_wb.sheet1
            
            logger.info("sheets_connected")
        except Exception as e:
            logger.error("sheets_connection_failed", error=str(e))
            raise
    
    def get_all_profiles(self) -> List[dict]:
        records = self.input_sheet.get_all_records()
        return [
            {"name": r.get("name"), "linkedin_url": r.get("linkedin_url")}
            for r in records
            if r.get("linkedin_url")
        ]
    
    def get_state_tracker_data(self) -> List[dict]:
        records = self.state_sheet.get_all_records()
        return records
    
    def initialize_state_tracker(self):
        """First run: populate state tracker from input sheet"""
        profiles = self.get_all_profiles()
        existing = {r["linkedin_url"] for r in self.get_state_tracker_data()}
        
        new_rows = []
        for profile in profiles:
            if profile["linkedin_url"] not in existing:
                new_rows.append([
                    profile["linkedin_url"],
                    "",
                    0,
                    0,
                    0,
                    "active",
                    ""
                ])
        
        if new_rows:
            self.state_sheet.append_rows(new_rows)
            logger.info("state_tracker_initialized", new_profiles=len(new_rows))
    
    def update_profile_state(
        self,
        linkedin_url: str,
        last_engaged_date: Optional[datetime] = None,
        increment_engagement: bool = False,
        increment_skip: bool = False,
        reset_skips: bool = False,
        status: Optional[str] = None,
        last_post_date: Optional[datetime] = None
    ):
        try:
            cell = self.state_sheet.find(linkedin_url)
            if not cell:
                logger.warning("profile_not_found_in_tracker", url=linkedin_url)
                return
            
            row = cell.row
            
            if last_engaged_date:
                self.state_sheet.update_cell(row, 2, last_engaged_date.isoformat())
            
            if increment_engagement:
                current = int(self.state_sheet.cell(row, 3).value or 0)
                self.state_sheet.update_cell(row, 3, current + 1)
            
            if increment_skip:
                current = int(self.state_sheet.cell(row, 4).value or 0)
                self.state_sheet.update_cell(row, 4, current + 1)
            
            if reset_skips:
                self.state_sheet.update_cell(row, 4, 0)
            
            if status:
                self.state_sheet.update_cell(row, 6, status)
            
            if last_post_date:
                self.state_sheet.update_cell(row, 7, last_post_date.isoformat())
                
        except Exception as e:
            logger.error("update_state_failed", url=linkedin_url, error=str(e))
    
    def log_engagement(
        self,
        name: str,
        linkedin_url: str,
        action_type: str,
        post_id: str,
        post_content: str,
        status: str,
        error_message: str = ""
    ):
        now = datetime.now()
        row = [
            now.isoformat(),
            name,
            linkedin_url,
            action_type,
            post_id,
            post_content[:200] if post_content else "",
            status,
            error_message,
            now.isocalendar()[1],
            now.strftime("%A")
        ]
        
        try:
            self.log_sheet.append_row(row)
            logger.info("engagement_logged", url=linkedin_url, status=status)
        except Exception as e:
            logger.error("log_engagement_failed", error=str(e))


_client_instance = None

def get_sheets_client() -> SheetsClient:
    global _client_instance
    if _client_instance is None:
        _client_instance = SheetsClient()
        _client_instance.connect()
    return _client_instance


def generate_daily_queue():
    from src.priority import rank_profiles, select_daily_queue
    
    client = get_sheets_client()
    
    client.initialize_state_tracker()
    
    state_data = client.get_state_tracker_data()
    
    ranked = rank_profiles(state_data)
    
    queue = select_daily_queue(ranked, limit=20)
    
    print("\n" + "="*50)
    print("TODAY'S ENGAGEMENT QUEUE")
    print("="*50)
    for i, profile in enumerate(queue, 1):
        print(f"{i:2}. {profile.name[:30]:30} | Score: {profile.priority_score:.1f}")
    print("="*50 + "\n")
    
    return queue


def show_queue():
    queue = generate_daily_queue()
    return queue


def test_connection():
    try:
        client = get_sheets_client()
        profiles = client.get_all_profiles()
        print(f"Connected successfully - Found {len(profiles)} profiles")
    except Exception as e:
        print(f"Connection failed: {e}")
```

---

## Section 6.1: n8n Execute Command

**For engagement action:**
```bash
cd /path/to/linkedin-automation && ./venv/bin/python main.py --url "{{ $json.linkedin_url }}" --name "{{ $json.name }}"
```

**For noise action:**
```bash
cd /path/to/linkedin-automation && ./venv/bin/python main.py --action noise
```

**main.py entry point:**

```python
import asyncio
import argparse
import json
import sys

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

from src.engagement import LinkedInEngagement
from src.noise_actions import perform_noise_action
from src.sheets_client import get_sheets_client

async def engage_profile(url: str, name: str, dry_run: bool = False):
    engagement = LinkedInEngagement()
    
    try:
        await engagement.initialize()
        result = await engagement.engage(url, dry_run=dry_run)
        
        client = get_sheets_client()
        
        client.log_engagement(
            name=name,
            linkedin_url=url,
            action_type=result.action_type or "",
            post_id=result.post_id or "",
            post_content=result.post_content or "",
            status="success" if result.success else "failed",
            error_message=result.error_message or ""
        )
        
        if result.success:
            client.update_profile_state(
                linkedin_url=url,
                last_engaged_date=result.timestamp,
                increment_engagement=True,
                reset_skips=True
            )
        else:
            client.update_profile_state(
                linkedin_url=url,
                increment_skip=True
            )
        
        print(json.dumps(result.to_dict()))
        return result
        
    finally:
        await engagement.close()


async def run_noise():
    engagement = LinkedInEngagement()
    
    try:
        await engagement.initialize()
        await perform_noise_action(engagement.page)
        print(json.dumps({"action": "noise", "success": True}))
    finally:
        await engagement.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="LinkedIn profile URL")
    parser.add_argument("--name", default="", help="Profile name")
    parser.add_argument("--action", choices=["engage", "noise"], default="engage")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually click")
    parser.add_argument("--test-batch", type=int, help="Test with N profiles")
    
    args = parser.parse_args()
    
    if args.action == "noise":
        asyncio.run(run_noise())
    elif args.test_batch:
        from src.sheets_client import generate_daily_queue
        queue = generate_daily_queue()[:args.test_batch]
        for profile in queue:
            asyncio.run(engage_profile(profile.linkedin_url, profile.name, args.dry_run))
    elif args.url:
        asyncio.run(engage_profile(args.url, args.name, args.dry_run))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
```

---

## Section 6.2: n8n Workflow JSON

```json
{
  "name": "LinkedIn Daily Engagement",
  "nodes": [
    {
      "parameters": {
        "rule": {
          "interval": [
            {
              "triggerAtHour": 9,
              "triggerAtMinute": 0
            }
          ]
        }
      },
      "name": "Schedule Trigger",
      "type": "n8n-nodes-base.scheduleTrigger",
      "position": [250, 300],
      "typeVersion": 1
    },
    {
      "parameters": {
        "command": "cd /path/to/linkedin-automation && ./venv/bin/python -c \"from src.sheets_client import generate_daily_queue; generate_daily_queue()\""
      },
      "name": "Generate Queue",
      "type": "n8n-nodes-base.executeCommand",
      "position": [450, 300],
      "typeVersion": 1
    },
    {
      "parameters": {
        "operation": "read",
        "sheetId": "YOUR_STATE_TRACKER_SHEET_ID",
        "range": "A:G",
        "options": {
          "valueRenderMode": "UNFORMATTED_VALUE"
        }
      },
      "name": "Read State Tracker",
      "type": "n8n-nodes-base.googleSheets",
      "position": [650, 300],
      "typeVersion": 4,
      "credentials": {
        "googleSheetsOAuth2Api": "YOUR_CREDENTIAL_ID"
      }
    },
    {
      "parameters": {
        "conditions": {
          "string": [
            {
              "value1": "={{ $json.status }}",
              "value2": "active"
            }
          ]
        }
      },
      "name": "Filter Active",
      "type": "n8n-nodes-base.filter",
      "position": [850, 300],
      "typeVersion": 1
    },
    {
      "parameters": {
        "batchSize": 1,
        "options": {}
      },
      "name": "Split In Batches",
      "type": "n8n-nodes-base.splitInBatches",
      "position": [1050, 300],
      "typeVersion": 2
    },
    {
      "parameters": {
        "command": "cd /path/to/linkedin-automation && ./venv/bin/python main.py --url \"{{ $json.linkedin_url }}\" --name \"{{ $json.name }}\"",
        "timeout": 120
      },
      "name": "Engage Profile",
      "type": "n8n-nodes-base.executeCommand",
      "position": [1250, 300],
      "typeVersion": 1
    },
    {
      "parameters": {
        "amount": "={{ Math.floor(Math.random() * 300) + 180 }}",
        "unit": "seconds"
      },
      "name": "Random Wait",
      "type": "n8n-nodes-base.wait",
      "position": [1450, 300],
      "typeVersion": 1
    },
    {
      "parameters": {
        "conditions": {
          "number": [
            {
              "value1": "={{ Math.random() }}",
              "operation": "smaller",
              "value2": 0.1
            }
          ]
        }
      },
      "name": "Noise Check",
      "type": "n8n-nodes-base.if",
      "position": [1650, 300],
      "typeVersion": 1
    },
    {
      "parameters": {
        "command": "cd /path/to/linkedin-automation && ./venv/bin/python main.py --action noise"
      },
      "name": "Noise Action",
      "type": "n8n-nodes-base.executeCommand",
      "position": [1850, 200],
      "typeVersion": 1
    }
  ],
  "connections": {
    "Schedule Trigger": {
      "main": [[{"node": "Generate Queue", "type": "main", "index": 0}]]
    },
    "Generate Queue": {
      "main": [[{"node": "Read State Tracker", "type": "main", "index": 0}]]
    },
    "Read State Tracker": {
      "main": [[{"node": "Filter Active", "type": "main", "index": 0}]]
    },
    "Filter Active": {
      "main": [[{"node": "Split In Batches", "type": "main", "index": 0}]]
    },
    "Split In Batches": {
      "main": [[{"node": "Engage Profile", "type": "main", "index": 0}]]
    },
    "Engage Profile": {
      "main": [[{"node": "Random Wait", "type": "main", "index": 0}]]
    },
    "Random Wait": {
      "main": [[{"node": "Noise Check", "type": "main", "index": 0}]]
    },
    "Noise Check": {
      "main": [
        [{"node": "Noise Action", "type": "main", "index": 0}],
        [{"node": "Split In Batches", "type": "main", "index": 0}]
      ]
    },
    "Noise Action": {
      "main": [[{"node": "Split In Batches", "type": "main", "index": 0}]]
    }
  }
}
```

---

## Section 7.1: systemd Service File

Save as `/etc/systemd/system/n8n.service`:

```ini
[Unit]
Description=n8n workflow automation
After=network.target

[Service]
Type=simple
User=your_username
WorkingDirectory=/home/your_username/linkedin-automation
ExecStart=/usr/bin/n8n start
Restart=on-failure
RestartSec=10
Environment=N8N_PORT=5678
Environment=GENERIC_TIMEZONE=America/New_York

[Install]
WantedBy=multi-user.target
```

---

## Section 8: src/noise_actions.py

```python
import random
import asyncio
from playwright.async_api import Page

import structlog

logger = structlog.get_logger()

NOISE_PROFILES = [
    "https://www.linkedin.com/in/satyanadella/",
    "https://www.linkedin.com/in/jeffweiner08/",
    "https://www.linkedin.com/in/raborchak/",
]

COMPANY_PAGES = [
    "https://www.linkedin.com/company/microsoft/",
    "https://www.linkedin.com/company/google/",
    "https://www.linkedin.com/company/amazon/",
]

async def perform_noise_action(page: Page):
    action = random.choice(["profile_visit", "feed_scroll", "company_visit"])
    
    logger.info("performing_noise_action", action=action)
    
    if action == "profile_visit":
        await _visit_random_profile(page)
    elif action == "feed_scroll":
        await _scroll_feed(page)
    elif action == "company_visit":
        await _visit_company_page(page)


async def _visit_random_profile(page: Page):
    url = random.choice(NOISE_PROFILES)
    await page.goto(url)
    
    await page.wait_for_timeout(random.randint(2000, 5000))
    
    scroll_amount = random.randint(300, 800)
    await page.evaluate(f"window.scrollTo(0, {scroll_amount})")
    
    await page.wait_for_timeout(random.randint(3000, 8000))
    
    logger.info("noise_profile_visited", url=url)


async def _scroll_feed(page: Page):
    await page.goto("https://www.linkedin.com/feed/")
    
    await page.wait_for_timeout(random.randint(2000, 4000))
    
    for _ in range(random.randint(3, 7)):
        scroll_amount = random.randint(400, 900)
        await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
        await page.wait_for_timeout(random.randint(1500, 4000))
    
    logger.info("noise_feed_scrolled")


async def _visit_company_page(page: Page):
    url = random.choice(COMPANY_PAGES)
    await page.goto(url)
    
    await page.wait_for_timeout(random.randint(2000, 5000))
    
    await page.evaluate("window.scrollTo(0, 500)")
    await page.wait_for_timeout(random.randint(2000, 6000))
    
    logger.info("noise_company_visited", url=url)
```

---

## Section 9: src/priority.py (Complete Module)

```python
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
            except:
                days_since = 999
        else:
            days_since = 999
        
        last_post_str = profile.get("last_post_date", "")
        if last_post_str:
            try:
                last_post = datetime.fromisoformat(last_post_str).date()
                post_days = (today - last_post).days
            except:
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
```
