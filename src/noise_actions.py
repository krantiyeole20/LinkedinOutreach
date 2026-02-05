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
