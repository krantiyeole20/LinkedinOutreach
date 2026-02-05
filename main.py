import asyncio
import argparse
import json
import sys

import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)

from src.engagement import LinkedInEngagement
from src.noise_actions import perform_noise_action
from src.sheets_client import get_sheets_client

async def engage_profile(url: str, name: str, dry_run: bool = False):
    engagement = LinkedInEngagement()
    
    try:
        await engagement.initialize()
        result = await engagement.engage(url, dry_run=dry_run)
        
        client = get_sheets_client()
        
        client.log_engagement(
            name=name,
            linkedin_url=url,
            action_type=result.action_type or "",
            post_id=result.post_id or "",
            post_content=result.post_content or "",
            status="success" if result.success else "failed",
            error_message=result.error_message or ""
        )
        
        if result.success:
            client.update_profile_state(
                linkedin_url=url,
                last_engaged_date=result.timestamp,
                increment_engagement=True,
                reset_skips=True
            )
        else:
            client.update_profile_state(
                linkedin_url=url,
                increment_skip=True
            )
        
        print(json.dumps(result.to_dict()))
        return result
        
    finally:
        await engagement.close()


async def run_noise():
    engagement = LinkedInEngagement()
    
    try:
        await engagement.initialize()
        await perform_noise_action(engagement.page)
        print(json.dumps({"action": "noise", "success": True}))
    finally:
        await engagement.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="LinkedIn profile URL")
    parser.add_argument("--name", default="", help="Profile name")
    parser.add_argument("--action", choices=["engage", "noise"], default="engage")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually click")
    parser.add_argument("--test-batch", type=int, help="Test with N profiles")
    
    args = parser.parse_args()
    
    if args.action == "noise":
        asyncio.run(run_noise())
    elif args.test_batch:
        from src.sheets_client import generate_daily_queue
        queue = generate_daily_queue()[:args.test_batch]
        for profile in queue:
            asyncio.run(engage_profile(profile.linkedin_url, profile.name, args.dry_run))
    elif args.url:
        asyncio.run(engage_profile(args.url, args.name, args.dry_run))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
