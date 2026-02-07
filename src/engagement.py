import asyncio
import json
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

import structlog

from config.settings import settings
from src.reaction_analyzer import get_analyzer, ReactionType
from src.scheduler import Scheduler

# Import from linkedin_scraper submodule
from linkedin_scraper.core.browser import BrowserManager
from linkedin_scraper.core.exceptions import AuthenticationError, RateLimitError, ScrapingError
from linkedin_scraper.scrapers import PersonPostsScraper

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
        self.browser_manager: Optional[BrowserManager] = None
        self.scraper: Optional[PersonPostsScraper] = None

    async def initialize(self):
        """Initialize browser and validate session via BrowserManager"""
        logger.info("initializing_engagement_engine")
        
        # Initialize BrowserManager
        self.browser_manager = BrowserManager(
            headless=settings.HEADLESS,
            viewport={
                "width": settings.VIEWPORT_WIDTH,
                "height": settings.VIEWPORT_HEIGHT
            }
        )
        
        await self.browser_manager.start()
        
        try:
            logger.info("loading_session", path=str(settings.SESSION_FILE))
            await self.browser_manager.load_session(str(settings.SESSION_FILE))
        except FileNotFoundError:
            logger.error("session_file_not_found", path=str(settings.SESSION_FILE))
            raise RuntimeError(f"Session file not found at {settings.SESSION_FILE}. Please run setup.")
        except Exception as e:
            logger.error("session_load_failed", error=str(e))
            raise RuntimeError(f"Failed to load session: {e}")

        # Initialize PersonPostsScraper with the page from BrowserManager
        self.scraper = PersonPostsScraper(self.browser_manager.page)
        logger.info("engagement_engine_ready")

    def _ensure_initialized(self):
        """Ensure browser and scraper are initialized"""
        if not self.browser_manager:
            raise RuntimeError("BrowserManager not initialized. Call initialize() first.")
        if not self.scraper:
            raise RuntimeError("Scraper not initialized. Call initialize() first.")

    async def engage(self, profile_url: str, dry_run: bool = False) -> EngagementResult:
        """
        Main engagement flow using PersonPostsScraper.
        Keeps existing scheduler, analyzer, and monitoring integration.
        """
        log = logger.bind(profile_url=profile_url)
        self._ensure_initialized()

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

            # Random noise action
            import random
            from src.noise_actions import perform_noise_action
            if random.random() < settings.NOISE_ACTION_PROBABILITY:
                 try:
                     logger.info("executing_noise_action")
                     await perform_noise_action(self.browser_manager.page)
                 except Exception as e:
                     logger.warning("noise_action_failed", error=str(e))

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



            # Use reaction analyzer (existing system)
            # Note: PersonPostsScraper currently only supports "Like", but we still use the analyzer 
            # to log what we *would* have done, or to decide if we should skip (if sentiment is bad?)
            # For now, we proceed with Like as the implementation only supports Like.
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
                action_type="Like",
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
        if self.browser_manager:
            await self.browser_manager.close()
