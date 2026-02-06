# LinkedinOutreach

Automated LinkedIn engagement system for strategic relationship building. Engages with posts from a curated list of 100 profiles using smart reactions, stochastic scheduling, and advanced anti-detection measures.

**Version 2.0** introduces stochastic weekly planning, coverage-first priority scoring, and continuous 7-day operation.

## System Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────────┐
│  Google Sheets  │────▶│   n8n (7 days)   │────▶│    LinkedinOutreach     │
│  (100 Profiles) │     │   Orchestrator   │     │    (Python Engine)      │
│                 │     │  Mon-Sun @ 9am   │     │                         │
└─────────────────┘     └──────────────────┘     └───────────┬─────────────┘
                                                             │
                        ┌────────────────────────────────────┼────────────────────────────────────┐
                        │                                    │                                    │
                        ▼                                    ▼                                    ▼
               ┌─────────────────┐               ┌─────────────────────┐              ┌──────────────────┐
               │ linkedin_scraper│               │  Smart Reactions    │              │  Scheduler       │
               │ (PersonPosts    │               │  (sentence-         │              │  (Stochastic     │
               │  Scraper)       │               │   transformers)     │              │   Weekly Plans)  │
               └────────┬────────┘               └─────────────────────┘              └──────────────────┘
                        │
                        ▼
               ┌─────────────────┐               ┌─────────────────────┐              ┌──────────────────┐
               │    LinkedIn     │               │   Timing Engine     │              │  Health Monitor  │
               │   (Playwright)  │               │  (Poisson Process)  │              │  (Circuit Breaker)│
               └─────────────────┘               └─────────────────────┘              └──────────────────┘
```

## Constraints

| Limit | Value | Enforcement |
|-------|-------|-------------|
| Daily | 20 engagements | Counter-based hard limit (resets midnight EST) |
| Weekly | 80 engagements | Stochastic budget allocation (resets Monday) |
| Hourly | 5 engagements | Burst protection |
| Operating hours | 9am - 6pm EST | Schedule trigger (all 7 days) |
| Days active | **7 days/week** | n8n runs Mon-Sun (continuous operation) |
| Profile rotation | ~14 days full cycle | Coverage-first priority scoring with forced inclusion |
| Daily budget variance | 5-20 engagements/day | Stochastic sampling from TruncatedNormal distribution |

---

## Project Structure

```
LinkedinOutreach/
├── linkedin_scraper/              # Submodule: github.com/joeyism/linkedin_scraper (forked)
│   └── linkedin_scraper/
│       └── scrapers/
│           └── person_posts.py    # Custom: PersonPostsScraper class
├── src/
│   ├── __init__.py
│   ├── engine.py                  # Main engagement engine (wraps PersonPostsScraper)
│   ├── engagement.py              # LinkedInEngagement class (integration layer)
│   ├── smart_reactions.py         # Sentence-transformers reaction selection
│   ├── scheduler.py               # **NEW: Stochastic weekly scheduler (replaces rate_limiter)**
│   ├── scorer.py                  # **NEW: Coverage-first priority scoring**
│   ├── timing.py                  # **NEW: Poisson-distributed timestamp generation**
│   ├── weekly_plan.py             # **NEW: Data models for WeeklyPlan, DailySlot, ScheduledEngagement**
│   ├── sheets_client.py           # Google Sheets read/write
│   ├── noise_actions.py           # Anti-detection behaviors
│   └── monitoring.py              # Health scoring & circuit breaker
├── config/
│   ├── settings.py                # All configuration (includes stochastic scheduler params)
│   └── credentials.json           # Google API service account key
├── n8n/
│   └── LinkedIn Outreach.json     # **NEW: Production 7-day workflow (13 nodes)**
├── tests/
│   ├── test_scheduler_sim.py      # **NEW: Monte Carlo coverage simulation**
│   ├── test_scorer_sim.py         # **NEW: Priority score distribution validation**
│   └── test_timing_sim.py         # **NEW: Poisson timing validation**
├── logs/
│   └── engagement.log
├── linkedin_session.json          # Saved browser session (from linkedin_scraper)
├── schedule_state.json            # **NEW: Persisted weekly plan (replaces rate_limit_state.json)**
├── main.py                        # CLI entry point (called by n8n)
├── requirements.txt
├── README.md
├── plan.md                        # Implementation plan for stochastic scheduler
└── N8N_WORKFLOW_GUIDE.md          # **NEW: Complete n8n setup guide for 7-day operation**
```

---

## Quick Start

### 1. Clone & Setup

```bash
git clone https://github.com/your-org/LinkedinOutreach.git
cd LinkedinOutreach

# Initialize submodule
git submodule update --init --recursive

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Install linkedin_scraper as editable
cd linkedin_scraper && pip install -e . && cd ..
```

### 2. Configure Google Sheets

1. Create Google Cloud project, enable Sheets API
2. Create service account, download JSON key
3. Save as `config/credentials.json`
4. Create 3 sheets and share with service account email:
   - `LinkedIn_Profiles_Input` (name, linkedin_url)
   - `LinkedIn_Engagement_Log` (tracking)
   - `LinkedIn_State_Tracker` (rotation state)

### 3. Authenticate LinkedIn

```bash
python -m src.engine --setup-session
```

Browser opens → log in manually → complete 2FA if prompted → press Enter in terminal.

Session saved to `linkedin_session.json` (valid ~30 days).

### 4. Generate Weekly Plan

```bash
# Generate stochastic weekly plan (Mon-Sun, 7 days)
python main.py --generate-week

# View the plan
python main.py --show-plan
```

### 5. Test Execution

```bash
# Dry run (no actual engagement)
python main.py --batch --dry-run

# Small live test (3 profiles)
python main.py --test-batch 3

# Full daily batch (uses today's schedule from weekly plan)
python main.py --batch
```

### 6. Setup n8n Workflow

See **[N8N_WORKFLOW_GUIDE.md](N8N_WORKFLOW_GUIDE.md)** for complete setup instructions.

---

## Core Components

### Scheduler (src/scheduler.py) - **NEW: Stochastic Weekly Planner**

Replaces the legacy token bucket rate limiter with a stochastic weekly planning system.

```python
from src.scheduler import Scheduler

scheduler = Scheduler()

# Generate weekly plan (Monday, or first run)
plan = scheduler.generate_weekly_plan(state_data)
# Creates 7-day plan with stochastic budget allocation
# Example: Mon:17, Tue:11, Wed:14, Thu:8, Fri:16, Sat:6, Sun:8 = 80 total

# Get today's queue (any day of week)
queue = scheduler.get_todays_queue()
# Returns: List[ScheduledEngagement] with scheduled_time for each profile

# Check limits (same interface as old RateLimiter)
can_proceed, info = scheduler.check_limits()

# Consume token
scheduler.consume()

# Mark outcome
scheduler.mark_outcome(linkedin_url, "done")  # or "skipped", "failed", "already_reacted", "no_posts"
```

**What it does:**
1. **Monday (or first run):** Generates stochastic weekly plan
   - Scores all 100 profiles using coverage-first algorithm
   - Samples 7 daily budgets from TruncatedNormal(mean=12, std=4, min=5, max=20)
   - Force-includes profiles not engaged for >12 days (up to 5/day)
   - Weighted random sampling for remaining slots
   - Assigns Poisson-distributed timestamps for natural timing
2. **Daily:** Loads today's schedule from persisted plan
3. **Per-engagement:** Counter-based limit checks (replaces token bucket math)
4. **Coverage-first priority:** `days_since * 0.8` (capped at 12) - no recency bias
5. **Outcome tracking:** Updates plan status and triggers state updates

### Scorer (src/scorer.py) - **NEW: Coverage-First Priority**

Replaces legacy priority queue with coverage-first algorithm.

**Priority Score Formula (simplified, no recency bias):**
```
score = min(days_since_last_like * 0.8, 12.0)  # Coverage-first, capped at 12
      + uniform(0.0, 5.0)                      # Positive jitter only
```

**Selection algorithm:**
1. Remove profiles engaged yesterday (no consecutive days)
2. Force-include profiles with `days_since > 12` (up to 5/day)
3. Build pool of top 2×budget profiles
4. **Weighted random sample** from pool (not strict top-N)

Higher score = higher probability of selection. Full rotation: ~14 days guaranteed.

**Why no recency bonus?**
- Old system: +15 points if posted < 24h → heavily favored active posters
- New system: Coverage-driven, engagement agnostic to posting frequency
- Result: More natural, less detectable pattern

### Timing Engine (src/timing.py) - **NEW: Poisson Process**

Generates human-like intra-day timestamps.

```python
from src.timing import generate_daily_timestamps

timestamps = generate_daily_timestamps(n=15, operating_start=time(9,0), operating_end=time(18,0))
# Returns: [time(9,23), time(10,47), time(11,12), ..., time(17,35)]
```

**How it works:**
- Non-homogeneous Poisson process with time-varying rate
- Peak activity: 10am-12pm and 1pm-3pm (mid-morning & early afternoon)
- Lower activity: 9-10am, 5-6pm (start/end of day)
- Minimum 3-minute gap between consecutive engagements
- ±5 minute jitter per timestamp

**Why Poisson?**
- Old system: uniform random delays (3-8 min) → suspiciously regular
- New system: Natural clustering (3 likes in 20 min, then 2 hour gap)
- Matches real human LinkedIn browsing behavior

### Engine (src/engine.py)

Wraps `PersonPostsScraper` with smart reactions, scheduler integration, and monitoring.

```python
from src.engine import EngagementEngine

async def main():
    engine = EngagementEngine()
    await engine.initialize()

    result = await engine.engage("https://linkedin.com/in/someone")
    # Returns: EngagementResult with status, reaction_type, post_id, etc.

    await engine.close()
```

**What it does:**
1. Checks limits via scheduler (daily/weekly/hourly)
2. Fetches most recent post via `PersonPostsScraper.scrape_most_recent()`
3. Analyzes post content → selects reaction (Celebrate/Support/Love/Insightful/Funny/Like)
4. Performs reaction via extended `react_to_post()` method
5. Logs to Google Sheets
6. Updates health score and scheduler outcome
7. Optionally performs noise action

### Smart Reactions (src/smart_reactions.py)

Uses `sentence-transformers` to pick contextually appropriate reactions.

| Post Content | Reaction |
|--------------|----------|
| Promotion, new job, milestone | Celebrate |
| Struggling, layoff, challenges | Support |
| Inspiring, gratitude, passion | Love |
| Tips, insights, data, research | Insightful |
| Humor, memes, weekend vibes | Funny |
| Default / low confidence | Like |

```python
from src.smart_reactions import ReactionAnalyzer

analyzer = ReactionAnalyzer()
reaction, confidence = analyzer.analyze("Excited to announce my promotion to VP!")
# reaction = ReactionType.CELEBRATE, confidence = 0.82
```

**Fallback:** If confidence < 0.5, defaults to `Like`.

### Noise Actions (src/noise_actions.py)

10% chance per engagement cycle to perform non-engagement activity:
- Visit random profile (scroll, leave)
- Scroll LinkedIn feed
- Visit company page

Reduces detection risk by mimicking natural browsing.

### Monitoring (src/monitoring.py)

Health score system with circuit breaker.

| Event | Score Change |
|-------|--------------|
| Successful engagement | +1 |
| Failed engagement | -5 |
| Rate limit detected | -20 |
| CAPTCHA challenge | -30 |
| Session expired | -40 |

**Circuit Breaker:**
- Score < 50: Pause 24h
- Score < 30: Pause 72h, alert team
- Score < 10: Disable, manual review required

---

## n8n Workflow - **7-Day Continuous Operation**

### Trigger
- **Schedule:** 9am **Mon-Sun** EST (all 7 days, continuous operation)
- **Manual:** Execute workflow button

### Enhanced Flow (13 Nodes)
```
Cron (Daily 9AM, Mon-Sun)
    ↓
Health Check (circuit breaker status - fail if score < 50)
    ↓
Status (load counters + plan state)
    ↓
IF (Is Monday?)
  ├─ true  → Generate Week → Show Plan → Run Batch
  └─ false → Run Batch
              ↓
        Parse Results (extract success/failure counts from stdout)
              ↓
        Daily Report (formatted summary with emojis)
              ↓
        IF (Is Sunday?)
          ├─ true  → Weekly Summary Report
          └─ false → [end]
              ↓
        [On any node failure] → Format Error → Slack/Email Notification
```

**Key improvements over basic workflow:**
- ✅ **7-day operation** (not just Mon-Fri): spreads 80 engagements evenly
- ✅ **Health monitoring**: stops automation if circuit breaker triggers
- ✅ **Daily reporting**: automatic success rate tracking
- ✅ **Weekly summaries**: Sunday evening full-week audit
- ✅ **Error notifications**: Slack/Email alerts on failures
- ✅ **Structured metrics**: Parse Results node extracts stats from batch output

### Import Workflow

1. Start n8n: `n8n start`
2. Go to http://localhost:5678
3. Import `n8n/LinkedIn Outreach.json`
4. Configure Slack webhook (or disable notification node)
5. Set workflow to **Active**

**See [N8N_WORKFLOW_GUIDE.md](N8N_WORKFLOW_GUIDE.md) for complete setup instructions.**

---

## CLI Reference

```bash
# Setup session (one-time, repeat monthly)
python -m src.engine --setup-session

# ── Weekly Planning (Stochastic Scheduler) ──
# Generate weekly plan (auto-runs Monday via n8n)
python main.py --generate-week

# Show current weekly plan (all 7 days)
python main.py --show-plan

# View today's queue (scheduled engagements with timestamps)
python main.py --show-queue

# Check scheduler status (counters + plan state)
python main.py --status

# ── Execution ──
# Process daily batch (uses today's schedule from weekly plan)
python main.py --batch

# Dry-run batch (no actual engagement, safe testing)
python main.py --batch --dry-run

# Test batch (small live test)
python main.py --test-batch 3

# Single profile engagement
python main.py --url "https://linkedin.com/in/username"

# Single profile dry run
python main.py --url "https://linkedin.com/in/username" --dry-run

# ── Monitoring ──
# Check health score (circuit breaker status)
python -c "from src.monitoring import HealthMonitor; print(f'Health: {HealthMonitor().get_score()}')"

# Verify Sheets connection
python -c "from src.sheets_client import SheetsClient; print(f'Profiles: {len(SheetsClient().read_input_sheet())}')"
```

---

## Google Sheets Schema

### LinkedIn_Profiles_Input
| Column | Type | Description |
|--------|------|-------------|
| name | string | Display name |
| linkedin_url | string | Full profile URL |

### LinkedIn_Engagement_Log
| Column | Type | Description |
|--------|------|-------------|
| timestamp | datetime | When action occurred |
| name | string | Profile name |
| linkedin_url | string | Profile URL |
| action_type | string | Reaction type (Like/Celebrate/etc) |
| post_id | string | LinkedIn post URN |
| post_content | string | First 200 chars |
| status | string | success/failed/skipped |
| error_message | string | If failed |
| week_number | int | ISO week |
| day_of_week | string | Monday-Sunday |

### LinkedIn_State_Tracker
| Column | Type | Description |
|--------|------|-------------|
| linkedin_url | string | Profile URL (unique key) |
| last_engaged_date | datetime | Last successful engagement |
| engagement_count | int | Total engagements |
| consecutive_skips | int | Times skipped in a row |
| priority_score | float | Calculated priority |
| status | string | active/private/deleted/paused |
| last_post_date | datetime | When user last posted |

---

## Configuration (config/settings.py)

```python
# Rate limits (hard guardrails)
DAILY_LIMIT = 20
WEEKLY_LIMIT = 80
HOURLY_LIMIT = 5

# Schedule (7-day operation)
OPERATING_START = time(9, 0)      # Same for all 7 days
OPERATING_END = time(18, 0)       # Same for all 7 days
TIMEZONE = "America/New_York"

# Stochastic Scheduler (NEW)
WEEKLY_BUDGET_TARGET = 80         # Total engagements per week
DAILY_BUDGET_MEAN = 12            # Average per day (stochastic)
DAILY_BUDGET_STD = 4              # Variance (some days lighter/heavier)
DAILY_BUDGET_MIN = 5              # Minimum per day
DAILY_BUDGET_MAX = 20             # Maximum per day

# Coverage guarantee (NEW)
FORCE_INCLUDE_DAYS_THRESHOLD = 12 # Force-include if not engaged for >12 days
FORCE_INCLUDE_MAX_PER_DAY = 5     # Max forced inclusions per day
COVERAGE_GUARANTEE_DAYS = 14      # Target: every profile within 14 days

# Priority scoring (NEW)
PRIORITY_DAYS_WEIGHT = 0.8        # days_since multiplier (coverage-first)
PRIORITY_DAYS_CAP = 12.0          # Cap at ~15 days
PRIORITY_JITTER_MAX = 5.0         # Random jitter (positive only)
SELECTION_POOL_MULTIPLIER = 2     # Pool = budget * this for weighted sampling

# Timing (Poisson process parameters - NEW)
TIMING_RATE_MORNING_WARMUP = 0.6  # 9-10am (slower)
TIMING_RATE_MID_MORNING = 1.3     # 10am-12pm (peak)
TIMING_RATE_LUNCH_DIP = 0.8       # 12-1pm (lower)
TIMING_RATE_AFTERNOON_PEAK = 1.2  # 1-3pm (peak)
TIMING_RATE_AFTERNOON_WIND = 0.7  # 3-5pm (slower)
TIMING_RATE_END_OF_DAY = 0.4      # 5-6pm (slowest)
TIMING_MIN_GAP_MINUTES = 3        # Minimum time between engagements
TIMING_JITTER_MINUTES = 5         # ±5 min jitter per timestamp

# Delays (seconds) - used for manual/fallback delays
MIN_DELAY_SECONDS = 180
MAX_DELAY_SECONDS = 480
NOISE_ACTION_PROBABILITY = 0.10

# Smart reactions
REACTION_CONFIDENCE_THRESHOLD = 0.5
SENTENCE_TRANSFORMER_MODEL = "all-MiniLM-L6-v2"

# Browser
HEADLESS = True
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080
PAGE_TIMEOUT = 30000
```

---

## Error Handling

| Error | Cause | Recovery |
|-------|-------|----------|
| `SessionExpiredError` | Cookies invalid | Run `--setup-session` |
| `RateLimitExceeded` | Hit LinkedIn limit | Auto-pause, wait for refill |
| `ProfileNotFoundError` | Deleted/changed URL | Mark `deleted` in tracker |
| `CaptchaDetectedError` | Suspicious activity | Stop immediately, manual review |
| `NoPostsError` | User inactive | Mark `last_post_date`, skip |
| `ReactionFailedError` | Button not found | Log, try `Like` fallback |
| `HealthCheckFailed` | Circuit breaker triggered | n8n workflow stops, wait 24-48h |

All errors logged with full context to `logs/engagement.log`.

---

## Maintenance

### Daily (Automated via n8n workflow)
- n8n runs at 9am EST **Mon-Sun (all 7 days)**
- Health check verifies circuit breaker status
- Daily report logs success/failure rates
- All execution logs available in n8n UI

### Weekly (Automated)
- **Monday:** Generate weekly plan (stochastic budget allocation for 7 days)
- **Sunday:** Weekly summary report (full week audit)
- Review engagement log in Google Sheets
- Check success rate (target: >80%)
- Verify coverage: all 100 profiles engaged within 14 days

### Monthly
- **Refresh LinkedIn session:** `python -m src.engine --setup-session`
- Review health score trends in monitoring logs
- Audit profile coverage (run simulation: `python -m tests.test_scheduler_sim`)
- Clean file logs >90 days: `logs/engagement.log`
- Update private/deleted profiles in State Tracker sheet
- Verify Google Sheets API credentials still valid

### Quarterly
- Review and tune stochastic scheduler parameters:
  - If worst-case coverage > 16 days: reduce `FORCE_INCLUDE_DAYS_THRESHOLD` to 10
  - If LinkedIn warnings: reduce `DAILY_BUDGET_MAX` to 15, increase `MIN_DELAY_SECONDS` to 300
  - If weekends too active: reduce `DAILY_BUDGET_MIN` to 3
- Update `linkedin_scraper` submodule: `git submodule update --remote`
- Review n8n workflow execution time trends

---

## Troubleshooting

### "Session expired" errors
```bash
python -m src.engine --setup-session
```

### All engagements failing
1. Check `linkedin_session.json` exists
2. Try manual login in browser
3. Verify Playwright installed: `playwright install chromium`
4. Check health score: `python -c "from src.monitoring import HealthMonitor; print(HealthMonitor().get_score())"`

### Same profiles engaged repeatedly
1. Check State Tracker sheet is updating
2. Verify `last_engaged_date` column populated
3. Run `python main.py --show-plan` to debug selection
4. Verify `mark_outcome()` is being called (check engagement logs)

### No engagements scheduled for today
```bash
# Check if plan exists
python main.py --show-plan

# Generate new plan if needed (normally done automatically on Monday)
python main.py --generate-week
```

### LinkedIn security warning received
1. **Stop automation immediately** (set n8n workflow to inactive)
2. Wait 48-72 hours
3. Review LinkedIn account security page
4. Reduce `DAILY_LIMIT` to 10-12
5. Increase `MIN_DELAY_SECONDS` to 300
6. Increase `NOISE_ACTION_PROBABILITY` to 0.15
7. Refresh session: `python -m src.engine --setup-session`
8. Test with small batch: `python main.py --test-batch 3`

### Health check failing in n8n
- **Symptom:** Workflow stops at Health Check node
- **Cause:** Circuit breaker activated (health score < 50)
- **Action:** Wait 24-48 hours, check logs for root cause, refresh session if needed

---

## Development

### Running Simulations (validate scheduler behavior)

```bash
# Full coverage simulation (12 weeks, 50 Monte Carlo runs)
python -m tests.test_scheduler_sim --weeks 12 --runs 50

# Quick sanity check (4 weeks, 5 runs)
python -m tests.test_scheduler_sim --weeks 4 --runs 5

# Priority score distribution analysis
python -m tests.test_scorer_sim

# Timing distribution validation (Poisson process)
python -m tests.test_timing_sim
```

**What simulations validate:**
- Coverage guarantee: 100% of profiles engaged within 14 days
- Forced inclusion safety net: profiles stuck at >12 days get prioritized
- Timing patterns: non-uniform, human-like clustering
- Stochastic budget: daily variance creates unpredictable patterns

### Adding New Reaction Categories

Edit `src/smart_reactions.py`:

```python
REACTION_CATEGORIES = {
    ReactionType.CELEBRATE: [
        "new job announcement",
        "promotion excited",
        # Add more phrases...
    ],
    # Add new categories...
}
```

### Updating LinkedIn Selectors

If LinkedIn changes UI, update in `src/engine.py`:

```python
REACTION_SELECTORS = {
    "Celebrate": 'button[aria-label*="Celebrate"]',
    # Update selectors as needed...
}
```

### Testing Changes

```bash
# Test weekly plan generation
python main.py --generate-week
python main.py --show-plan

# Test single profile (dry run)
python main.py --url "https://linkedin.com/in/test" --dry-run

# Test batch execution (dry run, no actual engagement)
python main.py --batch --dry-run

# Test with visible browser (debugging)
# Set HEADLESS = False in config/settings.py
python main.py --url "https://linkedin.com/in/test"

# Test small live batch (3 real engagements)
python main.py --test-batch 3
```

### Tuning Stochastic Scheduler

Edit `config/settings.py`:

```python
# Make weekends lighter (reduce minimum)
DAILY_BUDGET_MIN = 3  # was 5

# Reduce variance (more consistent daily counts)
DAILY_BUDGET_STD = 2  # was 4

# Tighten coverage guarantee (engage sooner)
FORCE_INCLUDE_DAYS_THRESHOLD = 10  # was 12

# Increase pool diversity (more randomness in selection)
SELECTION_POOL_MULTIPLIER = 3  # was 2
```

After changes, validate with simulation:
```bash
python -m tests.test_scheduler_sim --weeks 8 --runs 20
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| playwright | 1.40+ | Browser automation |
| sentence-transformers | 2.2+ | Smart reaction analysis (NLP for reaction selection) |
| gspread | 5.12+ | Google Sheets API |
| google-auth | 2.25+ | Google authentication |
| structlog | 23.2+ | Structured logging |
| pytz | 2023.3+ | Timezone handling |
| tenacity | 8.2+ | Retry logic |
| numpy | 1.24+ | Stochastic sampling, Poisson process simulation |
| scipy | 1.11+ | TruncatedNormal distribution for budget sampling |

---

## Key Improvements in v2.0 (Stochastic Scheduler)

### What Changed from v1.0

| Component | v1.0 (Token Bucket) | v2.0 (Stochastic Scheduler) |
|-----------|---------------------|------------------------------|
| **Rate limiting** | Token bucket with refill logic | Counter-based with weekly pre-planning |
| **Priority scoring** | Recency-bonus-heavy (favored active posters) | Coverage-first (no posting frequency bias) |
| **Selection** | Strict top-N | Weighted random sampling from 2× pool |
| **Timing** | Uniform random delays (3-8 min) | Poisson process with time-varying rate |
| **Days active** | Mon-Fri (5 days) | Mon-Sun (7 days, continuous) |
| **Planning horizon** | Daily (reactive) | Weekly (proactive) |
| **Coverage guarantee** | ~1.25 weeks (best-effort) | 14 days (guaranteed via forced inclusion) |
| **Monitoring** | Basic status checks | Health check, daily reports, weekly summaries |
| **n8n workflow** | 5 nodes (basic) | 13 nodes (production-ready) |

### Why These Changes?

1. **Token buckets produce uniform patterns** → Detectable by anti-automation systems
2. **Recency bonus created feedback loop** → Always engaged same active posters
3. **Strict top-N selection is predictable** → Same profiles every week
4. **Uniform delays look robotic** → Natural browsing has clustering
5. **Weekday-only operation is suspicious** → Real humans use LinkedIn on weekends
6. **Daily planning can't guarantee coverage** → Some profiles go 20+ days without engagement

### Migration Notes

**If upgrading from v1.0:**
1. Delete `rate_limit_state.json` (replaced by `schedule_state.json`)
2. Update imports in custom code: `from src.scheduler import Scheduler` (replaces `RateLimiter`)
3. Re-import n8n workflow from `n8n/LinkedIn Outreach.json` (13 nodes vs 5)
4. Run initial plan generation: `python main.py --generate-week`
5. Set n8n workflow to trigger **all 7 days** (not just Mon-Fri)
6. First week: monitor closely, expect ~11 engagements/day (vs 16/day before)

**Rollback plan:**
- Old files (`src/rate_limiter.py`, `src/priority_queue.py`) are deprecated but not deleted
- To rollback: revert imports in `src/engagement.py` and `src/engine.py`

---

## Team Contacts

- **Project Owner:** [Your Name]
- **Repository:** github.com/your-org/LinkedinOutreach
- **Slack:** #linkedin-automation
- **Documentation:** See [plan.md](plan.md) for implementation details, [N8N_WORKFLOW_GUIDE.md](N8N_WORKFLOW_GUIDE.md) for n8n setup

---

## License

Internal use only. Do not distribute.

---

**Last Updated:** February 2026
**Version:** 2.0.0 (Stochastic Scheduler, 7-Day Continuous Operation)
