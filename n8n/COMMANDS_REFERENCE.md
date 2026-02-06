# Execute Command Node Commands Reference

If commands don't import properly, copy-paste these into each node manually.

---

## Node 3: Health Check

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python -c "
import json, sys
try:
    from src.monitoring import HealthMonitor
    monitor = HealthMonitor()
    can_proceed = monitor.can_proceed()
    score = monitor.score
    resume = str(monitor.time_until_resume())
    result = {
        'health_score': score,
        'can_proceed': can_proceed,
        'time_until_resume': resume,
        'status': 'healthy' if can_proceed else 'paused'
    }
    print(json.dumps(result))
    if not can_proceed:
        print(f'CIRCUIT BREAKER OPEN: score={score}, resume_in={resume}', file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(json.dumps({'error': str(e), 'status': 'error'}))
    sys.exit(1)
"
```

---

## Node 4: Load Status

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python main.py --status 2>&1
```

---

## Node 6: Generate Weekly Plan

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python main.py --generate-week 2>&1
```

---

## Node 7: Show Plan (Audit Log)

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python main.py --show-plan 2>&1
```

---

## Node 9: Regenerate Plan (Recovery)

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python main.py --generate-week 2>&1
```

---

## Node 10: Run Batch

**For first test (dry run):**
```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python main.py --batch --dry-run 2>&1
```

**For production:**
```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python main.py --batch 2>&1
```

---

## Node 12: Daily Report

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python -c "
import json, sys

stats_raw = sys.argv[1] if len(sys.argv) > 1 else '{}'
try:
    stats = json.loads(stats_raw)
except:
    stats = {}

date = stats.get('date', 'unknown')
dow = stats.get('day_of_week', 'unknown')
done = stats.get('done', 0)
failed = stats.get('failed', 0)
skipped = stats.get('skipped', 0)
ar = stats.get('already_reacted', 0)
np = stats.get('no_posts', 0)
total = stats.get('total', 0)
rate = stats.get('success_rate', '0%')

report = f'''
=== DAILY REPORT: {date} ({dow}) ===
Total Attempts: {total}
  Done:            {done}
  Failed:          {failed}
  Skipped:         {skipped}
  Already Reacted: {ar}
  No Posts:        {np}
Success Rate:      {rate}
===================================
'''

print(report)

# Write summary to sheets
try:
    from src.sheets_client import get_sheets_client
    client = get_sheets_client()
    from datetime import datetime
    client.log_sheet.append_row([
        datetime.now().isoformat(),
        'DAILY_SUMMARY',
        '',
        f'done={done} failed={failed} ar={ar} np={np}',
        '',
        f'total={total} rate={rate}',
        'summary',
        '',
        datetime.now().isocalendar()[1],
        dow
    ])
    print('Summary logged to Sheets')
except Exception as e:
    print(f'Sheets logging failed: {e}', file=sys.stderr)
" '{{ JSON.stringify($json) }}'
```

---

## Node 14: Weekly Summary

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" && python -c "
import json
from src.scheduler import Scheduler

try:
    scheduler = Scheduler()
    plan = scheduler.plan
    status = scheduler.status()

    if plan:
        day_summaries = []
        total_done = 0
        total_budget = 0
        for date_key, day_slot in sorted(plan.days.items()):
            completed = day_slot.completed
            budget = day_slot.budget
            total_done += completed
            total_budget += budget
            day_summaries.append(f'  {date_key}: {completed}/{budget}')

        days_str = chr(10).join(day_summaries)
        rate = (total_done / max(total_budget, 1)) * 100

        print(f'''
{'='*45}
  WEEKLY SUMMARY - WEEK {plan.week_number}
{'='*45}
Week Start: {plan.week_start}
Budget:     {total_budget} engagements
Completed:  {total_done}/{total_budget} ({rate:.1f}%)

Daily Breakdown:
{days_str}

Rate Limits: {json.dumps(status, indent=2)}
{'='*45}
''')
    else:
        print('No weekly plan found')

except Exception as e:
    print(f'Weekly summary error: {e}')
" 2>&1
```

---

## Quick Copy-Paste List

If you need to paste them quickly:

1. **Health Check**: Python health monitor check (exits with code 1 if unhealthy)
2. **Load Status**: `python main.py --status 2>&1`
3. **Generate Weekly Plan**: `python main.py --generate-week 2>&1`
4. **Show Plan**: `python main.py --show-plan 2>&1`
5. **Regenerate Plan**: `python main.py --generate-week 2>&1` (same as #3)
6. **Run Batch**: `python main.py --batch 2>&1` (use `--dry-run` for testing)
7. **Daily Report**: Python script that formats and logs to Sheets
8. **Weekly Summary**: Python script that loads full week stats

All commands start with:
```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && source ".venv/bin/activate" &&
```
