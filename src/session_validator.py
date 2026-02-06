"""
LinkedIn session validation - checks if cookies are still valid
"""
import asyncio
from typing import Tuple
from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

import structlog

logger = structlog.get_logger()


class SessionValidator:
    """Validates LinkedIn session by checking for login indicators"""

    # URLs to check
    FEED_URL = "https://www.linkedin.com/feed/"
    LOGIN_CHECK_URL = "https://www.linkedin.com/feed/"

    # Selectors that indicate we're logged IN
    LOGGED_IN_SELECTORS = [
        'a[href*="/me/"]',  # Profile "Me" link in nav
        'button[aria-label*="Start a post"]',  # Post creation button
        'div.feed-identity-module',  # Profile card in feed
        'nav.global-nav',  # Main navigation bar
    ]

    # Selectors that indicate we're logged OUT
    LOGGED_OUT_SELECTORS = [
        'form.login__form',  # Login form
        'input[name="session_key"]',  # Email input on login page
        'input[name="session_password"]',  # Password input on login page
        'a[data-tracking-control-name*="guest"]',  # Guest links
    ]

    def __init__(self, page: Page):
        self.page = page

    async def is_logged_in(self) -> Tuple[bool, str]:
        """
        Check if session is still valid

        Returns:
            (is_valid, message)
        """
        try:
            # Navigate to feed (should be accessible if logged in)
            logger.info("checking_session", url=self.FEED_URL)
            await self.page.goto(self.FEED_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)  # Wait for dynamic content

            # Check for logged OUT indicators first (faster fail)
            for selector in self.LOGGED_OUT_SELECTORS:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        logger.warning("session_invalid", reason=f"Found logout indicator: {selector}")
                        return False, f"Session expired - found login form"
                except:
                    pass

            # Check for logged IN indicators
            found_indicators = []
            for selector in self.LOGGED_IN_SELECTORS:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        found_indicators.append(selector)
                except:
                    pass

            if len(found_indicators) >= 2:
                # Need at least 2 indicators to be confident
                logger.info("session_valid", indicators=len(found_indicators))
                return True, f"Session valid ({len(found_indicators)} indicators found)"
            else:
                logger.warning("session_uncertain", found=len(found_indicators), needed=2)
                return False, f"Session uncertain - only {len(found_indicators)} indicators found"

        except PlaywrightTimeout:
            logger.error("session_check_timeout")
            return False, "Session check timed out"
        except Exception as e:
            logger.error("session_check_error", error=str(e))
            return False, f"Session check failed: {str(e)[:50]}"

    async def quick_check(self) -> bool:
        """
        Quick check - just look at current page URL and title
        Useful if we're already on a LinkedIn page
        """
        try:
            url = self.page.url
            title = await self.page.title()

            # If we see these in URL or title, we're logged out
            logout_keywords = ['authwall', 'login', 'signup', 'checkpoint/lg']
            for keyword in logout_keywords:
                if keyword in url.lower() or keyword in title.lower():
                    logger.warning("quick_check_failed", reason=f"Found logout keyword: {keyword}")
                    return False

            # Quick selector check
            me_link = await self.page.query_selector('a[href*="/me/"]')
            if me_link:
                logger.debug("quick_check_passed")
                return True

            return False
        except:
            return False


async def validate_session(page: Page) -> Tuple[bool, str]:
    """
    Convenience function for one-time validation

    Returns:
        (is_valid, message)
    """
    validator = SessionValidator(page)
    return await validator.is_logged_in()
