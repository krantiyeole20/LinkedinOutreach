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