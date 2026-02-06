#!/usr/bin/env python3
"""
Test engagement flow using CSV data instead of Google Sheets
"""
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

from src.engagement import LinkedInEngagement

BASE_DIR = Path(__file__).parent

# Read first profile from CSV
csv_file = BASE_DIR / "LinkedIn_Profiles_Input.csv"
if not csv_file.exists():
    print(f"✗ CSV file not found: {csv_file}")
    sys.exit(1)

print("=" * 60)
print("LOADING PROFILES FROM CSV")
print("=" * 60)

profiles = []
with open(csv_file, 'r') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row.get('linkedin_url'):
            profiles.append({
                'url': row['linkedin_url'],
                'name': row.get('name', 'Unknown')
            })

print(f"Found {len(profiles)} profiles in CSV\n")

if not profiles:
    print("✗ No profiles found in CSV")
    sys.exit(1)

async def test_profile(profile_data, dry_run=True):
    """Test engagement with a single profile"""
    url = profile_data['url']
    name = profile_data['name']

    print("=" * 60)
    print(f"TESTING: {name}")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Time: {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60 + "\n")

    engagement = LinkedInEngagement()

    try:
        print("Initializing browser...")
        await engagement.initialize()
        print("✓ Browser ready\n")

        print("Starting engagement...")
        result = await engagement.engage(url, dry_run=dry_run)

        print("\n" + "=" * 60)
        print("RESULT")
        print("=" * 60)
        print(f"Success:  {result.success}")
        print(f"Action:   {result.action_type}")
        print(f"Post ID:  {result.post_id or 'N/A'}")
        if result.post_content:
            print(f"Post:     {result.post_content[:80]}...")
        print(f"Error:    {result.error_message or 'None'}")
        print("=" * 60 + "\n")

        return result

    except Exception as e:
        print(f"\n✗ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        await engagement.close()


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Run live (not dry run)')
    parser.add_argument('--count', type=int, default=1, help='Number of profiles to test')
    parser.add_argument('--delay', type=int, default=10, help='Delay between profiles (seconds)')
    args = parser.parse_args()

    dry_run = not args.live
    count = min(args.count, len(profiles))

    print(f"\nTesting {count} profile(s) in {'LIVE' if args.live else 'DRY RUN'} mode\n")

    results = []
    for i, profile in enumerate(profiles[:count], 1):
        print(f"\n{'='*60}")
        print(f"PROFILE {i}/{count}")
        print(f"{'='*60}\n")

        result = await test_profile(profile, dry_run=dry_run)
        results.append(result)

        if i < count:
            print(f"\nWaiting {args.delay} seconds before next profile...")
            await asyncio.sleep(args.delay)

    # Summary
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"Total tested: {count}")
    print(f"Successful:   {sum(1 for r in results if r and r.success)}")
    print(f"Failed:       {sum(1 for r in results if r and not r.success)}")
    print(f"Exceptions:   {sum(1 for r in results if r is None)}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
