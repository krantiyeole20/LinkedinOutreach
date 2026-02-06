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
from src.reaction_analyzer import get_analyzer, ReactionType
from src.scheduler import Scheduler
from src.session_validator import SessionValidator

# Import from linkedin_scraper submodule
from linkedin_scraper.scrapers import PersonPostsScraper
from linkedin_scraper.core.exceptions import AuthenticationError, RateLimitError, ScrapingError

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
    """
    LinkedIn engagement wrapper using PersonPostsScraper from linkedin_scraper submodule.
    Keeps existing interfaces for scheduler, analyzer, and monitoring systems.
    """

    def __init__(self):
        self.rate_limiter = Scheduler()
        self.analyzer = get_analyzer()
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.scraper: Optional[PersonPostsScraper] = None

    async def initialize(self):
        """Initialize browser and validate session"""
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

        # Initialize PersonPostsScraper
        self.scraper = PersonPostsScraper(self.page)

        # Validate session immediately after initialization
        validator = SessionValidator(self.page)
        is_valid, message = await validator.is_logged_in()
        if not is_valid:
            raise RuntimeError(f"LinkedIn session invalid: {message}")

    async def _load_cookies(self):
        """Load LinkedIn cookies from file"""
        if not settings.COOKIES_FILE.exists():
            raise FileNotFoundError(f"Cookies file not found: {settings.COOKIES_FILE}")

        with open(settings.COOKIES_FILE, "r") as f:
            cookies = json.load(f)

        await self.context.add_cookies(cookies)
        logger.info("cookies_loaded", count=len(cookies))

    async def engage(self, profile_url: str, dry_run: bool = False) -> EngagementResult:
        """
        Main engagement flow using PersonPostsScraper.
        Keeps existing scheduler, analyzer, and monitoring integration.
        """
        log = logger.bind(profile_url=profile_url)

        try:
            # Check rate limits (existing system)
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

            # Scrape most recent post using PersonPostsScraper
            try:
                post = await self.scraper.scrape_most_recent(profile_url)
            except AuthenticationError as e:
                log.error("authentication_error", error=str(e))
                return self._error_result(profile_url, "auth_error", "Session expired - please refresh cookies")
            except RateLimitError as e:
                log.error("scraper_rate_limit", error=str(e))
                return self._error_result(profile_url, "rate_limit", f"LinkedIn rate limit: {str(e)}")
            except ScrapingError as e:
                log.error("scraping_error", error=str(e))
                return self._error_result(profile_url, "scraping_failed", str(e))

            if not post:
                log.info("no_recent_post")
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "no_posts")
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

            # Check if already liked
            if post.already_liked:
                log.info("already_reacted")
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "already_reacted")
                return EngagementResult(
                    success=False,
                    profile_url=profile_url,
                    action_type=None,
                    post_id=post.urn,
                    post_content=post.text,
                    error_code="already_reacted",
                    error_message="Post already liked",
                    timestamp=datetime.now()
                )

            # Use reaction analyzer (existing system)
            reaction_type, confidence = self.analyzer.analyze(post.text)
            log.info("reaction_selected", reaction=reaction_type.value, confidence=confidence)

            # Dry run mode
            if dry_run:
                log.info("dry_run_skip_click")
                return EngagementResult(
                    success=True,
                    profile_url=profile_url,
                    action_type=f"DRY_RUN_{reaction_type.value}",
                    post_id=post.urn,
                    post_content=post.text,
                    error_code=None,
                    error_message=None,
                    timestamp=datetime.now()
                )

            # Perform like using PersonPostsScraper
            # Note: PersonPostsScraper.like_post() only does "Like", not other reactions
            # For now, we'll just use Like (can be extended later)
            success = await self.scraper.like_post(post.urn)

            if not success:
                log.error("like_failed", post_urn=post.urn)
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "failed")
                return self._error_result(profile_url, "like_failed", "Could not like post")

            # Update rate limiter (existing system)
            self.rate_limiter.consume()
            if hasattr(self.rate_limiter, "mark_outcome"):
                self.rate_limiter.mark_outcome(profile_url, "done")

            log.info("engagement_success", reaction="Like", post_id=post.urn)

            return EngagementResult(
                success=True,
                profile_url=profile_url,
                action_type="Like",  # PersonPostsScraper only does Like for now
                post_id=post.urn,
                post_content=post.text,
                error_code=None,
                error_message=None,
                timestamp=datetime.now()
            )

        except Exception as e:
            log.error("engagement_error", error=str(e))
            if hasattr(self.rate_limiter, "mark_outcome"):
                self.rate_limiter.mark_outcome(profile_url, "failed")
            return self._error_result(profile_url, "unexpected_error", str(e))

    def _error_result(self, profile_url: str, code: str, message: str) -> EngagementResult:
        """Helper to create error result"""
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
        """Cleanup resources"""
        if self.page:
            await self.page.close()
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
