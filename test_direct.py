#!/usr/bin/env python3
"""
Direct test script - bypasses Google Sheets, tests Playwright + engagement flow only
"""
import asyncio
import sys
from datetime import datetime

# Test 1: Can we import everything?
print("=" * 60)
print("TEST 1: Importing modules...")
print("=" * 60)

try:
    from src.engagement import LinkedInEngagement
    print("✓ LinkedInEngagement imported")
except Exception as e:
    print(f"✗ Failed to import LinkedInEngagement: {e}")
    sys.exit(1)

try:
    from playwright.async_api import async_playwright
    print("✓ Playwright imported")
except Exception as e:
    print(f"✗ Failed to import Playwright: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 2: Checking LinkedIn cookies/session")
print("=" * 60)

import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
cookies_file = BASE_DIR / "linkedin_cookies.json"
session_file = BASE_DIR / "linkedin_session.json"

if cookies_file.exists():
    print(f"✓ Found cookies file: {cookies_file}")
elif session_file.exists():
    print(f"✓ Found session file: {session_file}")
else:
    print("✗ No cookies or session file found!")
    print("  Run: python setup_session.py")
    sys.exit(1)

print("\n" + "=" * 60)
print("TEST 3: Dry run engagement test")
print("=" * 60)

# Test profile URL (use a real LinkedIn profile URL)
TEST_URL = "https://www.linkedin.com/in/williamhgates/"
TEST_NAME = "Bill Gates"

async def test_engagement():
    print(f"\nTarget: {TEST_NAME}")
    print(f"URL: {TEST_URL}")
    print(f"Mode: DRY RUN (no actual clicks)\n")

    engagement = LinkedInEngagement()

    try:
        print("Initializing browser...")
        await engagement.initialize()
        print("✓ Browser initialized\n")

        print("Starting engagement flow...")
        result = await engagement.engage(TEST_URL, dry_run=True)

        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)
        print(f"Success: {result.success}")
        print(f"Action: {result.action_type}")
        print(f"Post ID: {result.post_id or 'N/A'}")
        print(f"Post Content: {result.post_content[:100] if result.post_content else 'N/A'}...")
        print(f"Error: {result.error_message or 'None'}")
        print(f"Timestamp: {result.timestamp}")
        print("=" * 60)

        if result.success:
            print("\n✓ DRY RUN TEST PASSED")
            return True
        else:
            print(f"\n✗ DRY RUN FAILED: {result.error_message}")
            return False

    except Exception as e:
        print(f"\n✗ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        print("\nClosing browser...")
        await engagement.close()
        print("✓ Cleanup complete")

# Run test
if __name__ == "__main__":
    print(f"\nStarting test at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    success = asyncio.run(test_engagement())
    sys.exit(0 if success else 1)
