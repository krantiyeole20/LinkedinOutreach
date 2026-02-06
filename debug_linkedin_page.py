#!/usr/bin/env python3
"""
Debug script to inspect LinkedIn page structure
"""
import asyncio
import json
from playwright.async_api import async_playwright

async def debug():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )

        # Load cookies
        with open('linkedin_cookies.json') as f:
            cookies = json.load(f)
        await ctx.add_cookies(cookies)

        page = await ctx.new_page()

        # Go to activity page
        url = 'https://www.linkedin.com/in/rosalyn-santa-elena/recent-activity/all/'
        print(f"Navigating to: {url}")
        await page.goto(url, wait_until='domcontentloaded')

        print("Waiting 3 seconds...")
        await asyncio.sleep(3)

        # Scroll down to load posts
        print("Scrolling...")
        await page.evaluate("window.scrollTo(0, 500)")
        await asyncio.sleep(2)

        # Check for posts
        print("\nSearching for post containers...")
        posts = await page.query_selector_all('div.feed-shared-update-v2')
        print(f"  feed-shared-update-v2: {len(posts)}")

        posts2 = await page.query_selector_all('div[data-urn*="activity"]')
        print(f"  data-urn activity divs: {len(posts2)}")

        posts3 = await page.query_selector_all('article')
        print(f"  article tags: {len(posts3)}")

        # Check for reaction buttons
        print("\nSearching for reaction buttons...")
        buttons = await page.query_selector_all('button.reactions-react-button')
        print(f"  reactions-react-button: {len(buttons)}")

        buttons2 = await page.query_selector_all('button[aria-label*="React"]')
        print(f"  buttons with 'React' in aria-label: {len(buttons2)}")

        buttons3 = await page.query_selector_all('button[aria-label*="Like"]')
        print(f"  buttons with 'Like' in aria-label: {len(buttons3)}")

        # Get page title
        title = await page.title()
        print(f"\nPage title: {title}")

        # Check if we're logged in
        try:
            me_link = await page.query_selector('a[href*="/me/"]')
            if me_link:
                print("✓ Logged in (found 'me' link)")
            else:
                print("✗ Not logged in?")
        except:
            print("✗ Could not check login status")

        print("\nWaiting 30 seconds for manual inspection...")
        print("Browser window will stay open - check the page manually")
        await asyncio.sleep(30)

        await browser.close()
        print("Done")

if __name__ == "__main__":
    asyncio.run(debug())
