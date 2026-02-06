# src/engine.py
"""
Main engagement engine that wraps PersonPostsScraper with:
- Smart reaction selection
- Rate limiting
- Health monitoring
- Noise actions
- Google Sheets logging
"""

import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict
from enum import Enum

from playwright.async_api import Page, BrowserContext

import structlog

from linkedin_scraper import BrowserManager, PersonPostsScraper
from linkedin_scraper.models.post import Post

from config.settings import settings
from src.smart_reactions import ReactionAnalyzer, ReactionType
from src.scheduler import Scheduler
from src.monitoring import HealthMonitor, HealthEvent
from src.sheets_client import get_sheets_client
from src.noise_actions import perform_noise_action

logger = structlog.get_logger()


class EngagementStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RATE_LIMITED = "rate_limited"
    ALREADY_REACTED = "already_reacted"
    NO_POSTS = "no_posts"
    SESSION_EXPIRED = "session_expired"


@dataclass
class EngagementResult:
    status: EngagementStatus
    profile_url: str
    profile_name: str
    reaction_type: Optional[str]
    post_id: Optional[str]
    post_content: Optional[str]
    confidence: Optional[float]
    error_message: Optional[str]
    timestamp: datetime

    def to_dict(self) -> dict:
        result = asdict(self)
        result["status"] = self.status.value
        result["timestamp"] = self.timestamp.isoformat()
        return result


class EngagementEngine:
    """
    Main engine orchestrating LinkedIn engagement.
    
    Wraps PersonPostsScraper and adds:
    - Smart reaction selection via sentence-transformers
    - Rate limiting with token buckets
    - Health monitoring with circuit breaker
    - Noise actions for anti-detection
    """

    REACTION_PICKER_SELECTOR = "div.reactions-menu"
    REACTION_BUTTON_SELECTOR = "button.reactions-react-button"
    
    REACTION_SELECTORS = {
        ReactionType.LIKE: [
            'button[aria-label*="Like"]',
            'button.react-button__trigger[aria-label*="Like"]',
        ],
        ReactionType.CELEBRATE: [
            'button[aria-label*="Celebrate"]',
            'button[aria-label*="celebrate"]',
        ],
        ReactionType.SUPPORT: [
            'button[aria-label*="Support"]',
            'button[aria-label*="support"]',
        ],
        ReactionType.LOVE: [
            'button[aria-label*="Love"]',
            'button[aria-label*="love"]',
        ],
        ReactionType.INSIGHTFUL: [
            'button[aria-label*="Insightful"]',
            'button[aria-label*="insightful"]',
        ],
        ReactionType.FUNNY: [
            'button[aria-label*="Funny"]',
            'button[aria-label*="funny"]',
        ],
    }

    def __init__(self):
        self.browser_manager: Optional[BrowserManager] = None
        self.scraper: Optional[PersonPostsScraper] = None
        self.page: Optional[Page] = None
        
        self.reaction_analyzer = ReactionAnalyzer()
        self.rate_limiter = Scheduler()
        self.health_monitor = HealthMonitor()
        self.sheets_client = get_sheets_client()
        
        self._initialized = False

    async def initialize(self):
        """Initialize browser and load session."""
        if self._initialized:
            return
        
        logger.info("initializing_engine")
        
        self.browser_manager = BrowserManager(headless=settings.HEADLESS)
        await self.browser_manager.__aenter__()
        
        session_file = Path(settings.SESSION_FILE)
        if not session_file.exists():
            raise FileNotFoundError(
                f"Session file not found: {session_file}. "
                "Run 'python -m src.engine --setup-session' first."
            )
        
        await self.browser_manager.load_session(str(session_file))
        logger.info("session_loaded")
        
        self.page = self.browser_manager.page
        self.scraper = PersonPostsScraper(self.page)
        
        self._initialized = True
        logger.info("engine_initialized")

    async def close(self):
        """Clean up browser resources."""
        if self.browser_manager:
            await self.browser_manager.__aexit__(None, None, None)
        self._initialized = False
        logger.info("engine_closed")

    async def engage(
        self,
        profile_url: str,
        profile_name: str = "",
        dry_run: bool = False
    ) -> EngagementResult:
        """
        Engage with most recent post from a profile.
        
        Flow:
        1. Check rate limits
        2. Check health score
        3. Fetch most recent post
        4. Analyze content → select reaction
        5. Perform reaction (unless dry_run)
        6. Log result
        7. Update state
        
        Args:
            profile_url: LinkedIn profile URL
            profile_name: Display name for logging
            dry_run: If True, skip actual engagement
            
        Returns:
            EngagementResult with status and details
        """
        log = logger.bind(profile_url=profile_url, name=profile_name)
        
        try:
            can_proceed, limit_info = self.rate_limiter.check_limits()
            if not can_proceed:
                log.warning("rate_limit_blocked", info=limit_info)
                return self._result(
                    EngagementStatus.RATE_LIMITED,
                    profile_url, profile_name,
                    error_message=f"Rate limit: {limit_info}"
                )
            
            if not self.health_monitor.can_proceed():
                log.warning("health_check_failed", score=self.health_monitor.score)
                return self._result(
                    EngagementStatus.FAILED,
                    profile_url, profile_name,
                    error_message="Health score too low - paused"
                )
            
            log.info("fetching_recent_post")
            post = await self.scraper.scrape_most_recent(profile_url)
            
            if not post:
                log.info("no_posts_found")
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "no_posts")
                self._update_state_no_posts(profile_url)
                return self._result(
                    EngagementStatus.NO_POSTS,
                    profile_url, profile_name,
                    error_message="No recent posts found"
                )
            
            if post.already_liked:
                log.info("already_reacted", post_id=post.urn)
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "already_reacted")
                return self._result(
                    EngagementStatus.ALREADY_REACTED,
                    profile_url, profile_name,
                    post_id=post.urn,
                    post_content=post.text,
                    error_message="Already reacted to most recent post"
                )
            
            reaction_type, confidence = self.reaction_analyzer.analyze(post.text)
            log.info("reaction_selected", 
                    reaction=reaction_type.value, 
                    confidence=round(confidence, 2))
            
            if dry_run:
                log.info("dry_run_complete")
                return self._result(
                    EngagementStatus.SUCCESS,
                    profile_url, profile_name,
                    reaction_type=f"DRY_RUN_{reaction_type.value}",
                    post_id=post.urn,
                    post_content=post.text,
                    confidence=confidence
                )
            
            success = await self._perform_reaction(post, reaction_type)
            
            if success:
                self.rate_limiter.consume()
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "done")
                self.health_monitor.record(HealthEvent.SUCCESS)
                self._update_state_success(profile_url, post)
                
                log.info("engagement_success", 
                        reaction=reaction_type.value,
                        post_id=post.urn)
                
                return self._result(
                    EngagementStatus.SUCCESS,
                    profile_url, profile_name,
                    reaction_type=reaction_type.value,
                    post_id=post.urn,
                    post_content=post.text,
                    confidence=confidence
                )
            else:
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "failed")
                self.health_monitor.record(HealthEvent.FAILURE)
                return self._result(
                    EngagementStatus.FAILED,
                    profile_url, profile_name,
                    post_id=post.urn,
                    post_content=post.text,
                    error_message="Failed to perform reaction"
                )
                
        except Exception as e:
            log.error("engagement_error", error=str(e), exc_info=True)
            if hasattr(self.rate_limiter, "mark_outcome"):
                self.rate_limiter.mark_outcome(profile_url, "failed")
            self.health_monitor.record(HealthEvent.FAILURE)
            return self._result(
                EngagementStatus.FAILED,
                profile_url, profile_name,
                error_message=str(e)
            )

    async def _perform_reaction(
        self, 
        post: Post, 
        reaction_type: ReactionType
    ) -> bool:
        """
        Perform reaction on a post.
        
        For LIKE: Simple click on reaction button.
        For others: Hover to open picker, then click specific reaction.
        
        Returns True if successful.
        """
        try:
            posts = await self.page.query_selector_all("div.feed-shared-update-v2")
            if not posts:
                logger.error("no_post_elements_found")
                return False
            
            post_element = posts[0]
            
            reaction_btn = await post_element.query_selector(self.REACTION_BUTTON_SELECTOR)
            if not reaction_btn:
                logger.error("reaction_button_not_found")
                return False
            
            await self._human_like_scroll(post_element)
            
            if reaction_type == ReactionType.LIKE:
                await self._human_like_click(reaction_btn)
                await self.page.wait_for_timeout(random.randint(500, 1000))
                return True
            
            await reaction_btn.hover()
            await self.page.wait_for_timeout(random.randint(800, 1500))
            
            picker = await self.page.wait_for_selector(
                self.REACTION_PICKER_SELECTOR,
                timeout=5000
            )
            
            if not picker:
                logger.warning("reaction_picker_not_found_falling_back_to_like")
                await self._human_like_click(reaction_btn)
                return True
            
            specific_btn = None
            for selector in self.REACTION_SELECTORS.get(reaction_type, []):
                specific_btn = await picker.query_selector(selector)
                if specific_btn:
                    break
            
            if specific_btn:
                await self._human_like_click(specific_btn)
                logger.info("specific_reaction_clicked", reaction=reaction_type.value)
            else:
                logger.warning("specific_reaction_not_found_using_like",
                             requested=reaction_type.value)
                await self._human_like_click(reaction_btn)
            
            await self.page.wait_for_timeout(random.randint(500, 1000))
            return True
            
        except Exception as e:
            logger.error("perform_reaction_error", error=str(e))
            return False

    async def _human_like_scroll(self, element):
        """Scroll element into view with human-like behavior."""
        await element.scroll_into_view_if_needed()
        await self.page.wait_for_timeout(random.randint(300, 700))
        
        jitter = random.randint(-50, 50)
        await self.page.evaluate(f"window.scrollBy(0, {jitter})")

    async def _human_like_click(self, element):
        """Click with human-like mouse movement."""
        box = await element.bounding_box()
        if box:
            target_x = box["x"] + box["width"] / 2 + random.randint(-3, 3)
            target_y = box["y"] + box["height"] / 2 + random.randint(-2, 2)
            
            await self.page.mouse.move(target_x, target_y, steps=random.randint(8, 20))
            await self.page.wait_for_timeout(random.randint(50, 150))
        
        await element.click()

    def _result(
        self,
        status: EngagementStatus,
        profile_url: str,
        profile_name: str,
        reaction_type: Optional[str] = None,
        post_id: Optional[str] = None,
        post_content: Optional[str] = None,
        confidence: Optional[float] = None,
        error_message: Optional[str] = None
    ) -> EngagementResult:
        """Create EngagementResult and log to sheets."""
        result = EngagementResult(
            status=status,
            profile_url=profile_url,
            profile_name=profile_name,
            reaction_type=reaction_type,
            post_id=post_id,
            post_content=post_content[:200] if post_content else None,
            confidence=confidence,
            error_message=error_message,
            timestamp=datetime.now()
        )
        
        try:
            self.sheets_client.log_engagement(
                name=profile_name,
                linkedin_url=profile_url,
                action_type=reaction_type or "",
                post_id=post_id or "",
                post_content=post_content or "",
                status=status.value,
                error_message=error_message or ""
            )
        except Exception as e:
            logger.error("sheets_log_failed", error=str(e))
        
        return result

    def _update_state_success(self, profile_url: str, post: Post):
        """Update state tracker after successful engagement."""
        try:
            self.sheets_client.update_profile_state(
                linkedin_url=profile_url,
                last_engaged_date=datetime.now(),
                increment_engagement=True,
                reset_skips=True,
                last_post_date=post.posted_date if hasattr(post, 'posted_date') else None
            )
        except Exception as e:
            logger.error("state_update_failed", error=str(e))

    def _update_state_no_posts(self, profile_url: str):
        """Update state tracker when no posts found."""
        try:
            self.sheets_client.update_profile_state(
                linkedin_url=profile_url,
                increment_skip=True
            )
        except Exception as e:
            logger.error("state_update_failed", error=str(e))

    async def perform_noise(self):
        """Execute a random noise action."""
        await perform_noise_action(self.page)

    def get_status(self) -> dict:
        """Get current engine status."""
        return {
            "rate_limits": self.rate_limiter.status(),
            "health_score": self.health_monitor.score,
            "can_proceed": self.health_monitor.can_proceed(),
            "initialized": self._initialized
        }


async def setup_session():
    """Interactive session setup - manual login."""
    print("\n" + "="*50)
    print("LINKEDIN SESSION SETUP")
    print("="*50)
    
    async with BrowserManager(headless=False) as browser:
        page = browser.page
        await page.goto("https://www.linkedin.com/login")
        
        print("\n1. Log into LinkedIn in the browser window")
        print("2. Complete any 2FA/CAPTCHA if prompted")
        print("3. Wait until you see your LinkedIn feed")
        print("4. Press ENTER here when done\n")
        
        input("Press ENTER after logging in...")
        
        session_file = Path(settings.SESSION_FILE)
        await browser.save_session(str(session_file))
        
        print(f"\nSession saved to: {session_file}")
        print("="*50 + "\n")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser()
    parser.add_argument("--setup-session", action="store_true")
    args = parser.parse_args()
    
    if args.setup_session:
        asyncio.run(setup_session())