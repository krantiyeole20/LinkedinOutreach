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
