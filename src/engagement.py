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
from src.scheduler import Scheduler

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
        self.rate_limiter = Scheduler()
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
            
            posts = await self.page.query_selector_all("div.feed-shared-update-v2")
            if not posts:
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "failed")
                return self._error_result(profile_url, "post_element_not_found", "Could not find post element")
            
            first_post = posts[0]
            reaction_state = await post_fetcher.get_reaction_button_state(first_post)
            
            if reaction_state.get("already_reacted"):
                log.info("already_reacted", current=reaction_state.get("current_reaction"))
                if hasattr(self.rate_limiter, "mark_outcome"):
                    self.rate_limiter.mark_outcome(profile_url, "already_reacted")
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
            if hasattr(self.rate_limiter, "mark_outcome"):
                self.rate_limiter.mark_outcome(profile_url, "done")

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
            if hasattr(self.rate_limiter, "mark_outcome"):
                self.rate_limiter.mark_outcome(profile_url, "failed")
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