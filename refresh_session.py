#!/usr/bin/env python3
"""
Refresh LinkedIn session - launch browser for manual login and save new cookies
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).parent
COOKIES_FILE = BASE_DIR / "linkedin_cookies.json"


async def refresh_session():
    print("=" * 60)
    print("LINKEDIN SESSION REFRESH")
    print("=" * 60)
    print("\nThis will:")
    print("1. Launch a browser window")
    print("2. Navigate to LinkedIn")
    print("3. Wait for you to log in manually")
    print("4. Save the new cookies")
    print("\nPress Ctrl+C to cancel, or press Enter to continue...")
    input()

    async with async_playwright() as p:
        print("\nLaunching browser...")
        browser = await p.chromium.launch(
            headless=False,  # Must be visible for manual login
            args=['--start-maximized']
        )

        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        page = await context.new_page()

        # Try to load existing cookies first
        if COOKIES_FILE.exists():
            print(f"Loading existing cookies from: {COOKIES_FILE}")
            with open(COOKIES_FILE) as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            print(f"✓ Loaded {len(cookies)} cookies")

        print("\nNavigating to LinkedIn...")
        await page.goto("https://www.linkedin.com/feed/")
        await asyncio.sleep(3)

        # Check if already logged in
        me_link = await page.query_selector('a[href*="/me/"]')
        if me_link:
            print("\n✓ You are already logged in!")
            print("\nIf you want to re-login, manually log out in the browser, then log back in.")
        else:
            print("\n⚠ You are NOT logged in")
            print("\nPlease log in to LinkedIn in the browser window...")

        print("\n" + "=" * 60)
        print("MANUAL ACTIONS REQUIRED:")
        print("=" * 60)
        print("1. Check if you're logged in (see your profile picture?)")
        print("2. If not logged in, complete the login process")
        print("3. If asked for 2FA, complete it")
        print("4. Navigate around a bit (click Feed, Notifications, etc.)")
        print("5. When done, come back here and press Enter")
        print("=" * 60)
        input("\nPress Enter when you're fully logged in...")

        # Verify login
        print("\nVerifying login status...")
        await page.goto("https://www.linkedin.com/feed/")
        await asyncio.sleep(2)

        me_link = await page.query_selector('a[href*="/me/"]')
        if not me_link:
            print("\n✗ ERROR: Still not logged in!")
            print("Please try again and make sure you're fully logged in before pressing Enter")
            await browser.close()
            return

        print("✓ Login verified!")

        # Save cookies
        print(f"\nSaving cookies to: {COOKIES_FILE}")
        cookies = await context.cookies()

        # Backup old cookies
        if COOKIES_FILE.exists():
            backup_file = BASE_DIR / "linkedin_cookies.json.backup"
            print(f"Backing up old cookies to: {backup_file}")
            with open(COOKIES_FILE) as f:
                old_cookies = f.read()
            with open(backup_file, 'w') as f:
                f.write(old_cookies)

        # Save new cookies
        with open(COOKIES_FILE, 'w') as f:
            json.dump(cookies, f, indent=2)

        print(f"✓ Saved {len(cookies)} cookies")

        # Test the cookies
        print("\nTesting cookies by reloading page...")
        await page.goto("https://www.linkedin.com/feed/")
        await asyncio.sleep(2)

        me_link = await page.query_selector('a[href*="/me/"]')
        if me_link:
            print("✓ Cookies work! Session is valid.")
        else:
            print("✗ WARNING: Cookies might not work correctly")

        print("\n" + "=" * 60)
        print("SESSION REFRESH COMPLETE")
        print("=" * 60)
        print(f"\nCookies saved to: {COOKIES_FILE}")
        print(f"Cookie count: {len(cookies)}")
        print("\nYou can now run your automation scripts.")
        print("=" * 60)

        await asyncio.sleep(2)
        await browser.close()


if __name__ == "__main__":
    try:
        asyncio.run(refresh_session())
    except KeyboardInterrupt:
        print("\n\nCancelled by user")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
