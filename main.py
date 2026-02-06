import asyncio
import argparse
import json
import sys
from datetime import datetime
from typing import Optional

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

logger = structlog.get_logger()


async def engage_profile(url: str, name: str, dry_run: bool = False):
    engagement = LinkedInEngagement()

    try:
        await engagement.initialize()
        result = await engagement.engage(url, dry_run=dry_run)

        try:
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
        except Exception as e:
            logger.error("sheets_update_failed", error=str(e))

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
    except Exception as e:
        logger.error("noise_action_failed", error=str(e))
        print(json.dumps({"action": "noise", "success": False, "error": str(e)}))
    finally:
        await engagement.close()


def generate_weekly_plan():
    from src.scheduler import Scheduler

    try:
        client = get_sheets_client()
        client.initialize_state_tracker()
        state_data = client.get_state_tracker_data()
        profiles = client.get_all_profiles()
        profile_names = {p["linkedin_url"]: p.get("name", "") for p in profiles}
        for row in state_data:
            url = row.get("linkedin_url")
            if url and "name" not in row:
                row["name"] = profile_names.get(url, "")

        scheduler = Scheduler()
        plan = scheduler.generate_weekly_plan(state_data)
        print("\n" + "=" * 50)
        print("WEEKLY PLAN GENERATED")
        print("=" * 50)
        print(f"Week: {plan.week_number}, Total budget: {plan.total_budget}")
        for date_str, slot in sorted(plan.days.items()):
            print(f"  {date_str}: {slot.budget} engagements (burst={slot.is_burst_day})")
        print("=" * 50 + "\n")
    except Exception as e:
        logger.error("generate_plan_failed", error=str(e))
        raise


def show_plan():
    from src.scheduler import Scheduler

    try:
        scheduler = Scheduler()
        if scheduler.plan is None:
            print("No weekly plan loaded. Run --generate-week first.")
            return
        plan = scheduler.plan
        print("\n" + "=" * 50)
        print("CURRENT WEEKLY PLAN")
        print("=" * 50)
        print(f"Week: {plan.week_number}, Total budget: {plan.total_budget}")
        print(f"Created: {plan.created_at}")
        today_str = datetime.now().strftime("%Y-%m-%d")
        for date_str, slot in sorted(plan.days.items()):
            pending = [e for e in slot.engagements if e.status == "pending"]
            print(f"  {date_str}: {slot.completed}/{slot.budget} done, {len(pending)} pending")
            if date_str == today_str and pending:
                for e in pending[:5]:
                    print(f"    - {e.name[:30]:30} @ {e.scheduled_time.strftime('%H:%M')}")
                if len(pending) > 5:
                    print(f"    ... and {len(pending) - 5} more")
        print("=" * 50 + "\n")
    except Exception as e:
        logger.error("show_plan_failed", error=str(e))
        raise


async def run_batch(dry_run: bool = False, limit: Optional[int] = None):
    from src.scheduler import Scheduler
    from config.settings import settings

    try:
        scheduler = Scheduler()
        queue = scheduler.get_todays_queue()
        if not queue:
            print("No engagements scheduled for today.")
            return

        if limit:
            queue = queue[:limit]

        print(f"\nProcessing {len(queue)} profiles for today...")
        for i, engagement in enumerate(queue):
            try:
                await engage_profile(
                    engagement.linkedin_url,
                    engagement.name,
                    dry_run=dry_run,
                )
                if not dry_run and i < len(queue) - 1:
                    delay = settings.get_random_delay()
                    await asyncio.sleep(delay)
            except Exception as e:
                logger.error("batch_profile_failed", url=engagement.linkedin_url, error=str(e))
                if hasattr(scheduler, "mark_outcome"):
                    scheduler.mark_outcome(engagement.linkedin_url, "failed")
    except Exception as e:
        logger.error("batch_failed", error=str(e))
        raise


def show_status():
    from src.scheduler import Scheduler

    try:
        scheduler = Scheduler()
        s = scheduler.status()
        print("\n" + "=" * 40)
        print("SCHEDULER STATUS")
        print("=" * 40)
        print(f"Daily:   {s['daily']['used']}/{s['daily']['limit']}")
        print(f"Weekly:  {s['weekly']['used']}/{s['weekly']['limit']}")
        print(f"Hourly:  {s['hourly']['used']}/{s['hourly']['limit']}")
        print(f"Plan: {'Yes' if s['plan_exists'] else 'No'}, Week: {s['plan_week']}")
        print("=" * 40 + "\n")
    except Exception as e:
        logger.error("status_failed", error=str(e))
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="LinkedIn profile URL")
    parser.add_argument("--name", default="", help="Profile name")
    parser.add_argument("--action", choices=["engage", "noise"], default="engage")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually click")
    parser.add_argument("--test-batch", type=int, help="Test with N profiles")
    parser.add_argument("--batch", action="store_true", help="Run today's scheduled queue")
    parser.add_argument("--generate-week", action="store_true", help="Generate weekly plan")
    parser.add_argument("--show-plan", action="store_true", help="Show current weekly plan")
    parser.add_argument("--status", action="store_true", help="Show scheduler status")

    args = parser.parse_args()

    if args.status:
        show_status()
        return
    if args.generate_week:
        generate_weekly_plan()
        return
    if args.show_plan:
        show_plan()
        return
    if args.batch:
        asyncio.run(run_batch(dry_run=args.dry_run))
        return
    if args.action == "noise":
        asyncio.run(run_noise())
        return
    if args.test_batch:
        asyncio.run(run_batch(dry_run=args.dry_run, limit=args.test_batch))
        return
    if args.url:
        asyncio.run(engage_profile(args.url, args.name, args.dry_run))
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
