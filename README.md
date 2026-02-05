# LinkedinOutreach

Automated LinkedIn engagement system for strategic relationship building. Engages with posts from a curated list of 100 profiles using smart reactions, rate limiting, and anti-detection measures.

## System Overview

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────────┐
│  Google Sheets  │────▶│       n8n        │────▶│    LinkedinOutreach     │
│  (100 Profiles) │     │  (Orchestrator)  │     │    (Python Engine)      │
└─────────────────┘     └──────────────────┘     └───────────┬─────────────┘
                                                             │
                        ┌────────────────────────────────────┼────────────────────────────────────┐
                        │                                    │                                    │
                        ▼                                    ▼                                    ▼
               ┌─────────────────┐               ┌─────────────────────┐              ┌──────────────────┐
               │ linkedin_scraper│               │  Smart Reactions    │              │   Rate Limiter   │
               │ (PersonPosts    │               │  (sentence-         │              │  (Token Bucket)  │
               │  Scraper)       │               │   transformers)     │              │                  │
               └────────┬────────┘               └─────────────────────┘              └──────────────────┘
                        │
                        ▼
               ┌─────────────────┐
               │    LinkedIn     │
               │   (Playwright)  │
               └─────────────────┘
```

## Constraints

| Limit | Value | Enforcement |
|-------|-------|-------------|
| Daily | 20 engagements | Token bucket (resets midnight EST) |
| Weekly | 80 engagements | Token bucket (resets Monday midnight EST) |
| Hourly | 5 engagements | Burst protection |
| Operating hours | 9am - 6pm EST | Schedule trigger |
| Profile rotation | ~1.25 weeks full cycle | Priority queue algorithm |

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
│   ├── smart_reactions.py         # Sentence-transformers reaction selection
│   ├── rate_limiter.py            # Token bucket implementation
│   ├── priority_queue.py          # Profile prioritization logic
│   ├── sheets_client.py           # Google Sheets read/write
│   ├── noise_actions.py           # Anti-detection behaviors
│   └── monitoring.py              # Health scoring & circuit breaker
├── config/
│   ├── settings.py                # All configuration
│   └── credentials.json           # Google API service account key
├── logs/
│   └── engagement.log
├── linkedin_session.json          # Saved browser session (from linkedin_scraper)
├── rate_limit_state.json          # Persisted rate limit tokens
├── main.py                        # CLI entry point (called by n8n)
├── requirements.txt
└── README.md
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
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

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

### 4. Test Single Profile

```bash
# Dry run (no actual engagement)
python main.py --url "https://linkedin.com/in/satyanadella" --dry-run

# Live engagement
python main.py --url "https://linkedin.com/in/satyanadella"
```

### 5. Run Daily Batch

```bash
# Process today's queue (20 profiles)
python main.py --batch
```

---

## Core Components

### Engine (src/engine.py)

Wraps `PersonPostsScraper` with smart reactions, rate limiting, and monitoring.

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
1. Checks rate limits (daily/weekly/hourly)
2. Fetches most recent post via `PersonPostsScraper.scrape_most_recent()`
3. Analyzes post content → selects reaction (Celebrate/Support/Love/Insightful/Funny/Like)
4. Performs reaction via extended `react_to_post()` method
5. Logs to Google Sheets
6. Updates health score
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

### Rate Limiter (src/rate_limiter.py)

Triple token bucket with persistence.

```python
from src.rate_limiter import RateLimiter

limiter = RateLimiter()
can_proceed, info = limiter.check_limits()

if can_proceed:
    # do engagement
    limiter.consume()
else:
    print(f"Blocked: {info}")  # "daily_limit (0/20)"
```

State persisted to `rate_limit_state.json` across restarts.

### Priority Queue (src/priority_queue.py)

Ensures fair rotation across 100 profiles.

**Priority Score Formula:**
```
score = (days_since_engagement * 10) 
      + (consecutive_skips * 5) 
      + (recency_bonus)           # +15 if posted < 24h
      - (total_engagements * 0.5)
      + (random_jitter ±10)
```

Higher score = engaged sooner. Full rotation: ~1.25 weeks.

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

## PersonPostsScraper Integration

The `linkedin_scraper` submodule provides `PersonPostsScraper` for:
- Navigating to profile's recent activity
- Extracting most recent post (content, URN, timestamp)
- Liking posts

**We extend it** in `src/engine.py` to support all reaction types:

```python
# Original PersonPostsScraper only does Like
await scraper.like_post(post.urn)

# Our engine adds reaction selection
await engine._perform_reaction(post_element, ReactionType.CELEBRATE)
```

**Reaction button selectors** (hover to open picker, then click specific reaction):
```python
REACTION_SELECTORS = {
    "Like": 'button[aria-label*="Like"]',
    "Celebrate": 'button[aria-label*="Celebrate"]',
    "Support": 'button[aria-label*="Support"]',
    "Love": 'button[aria-label*="Love"]',
    "Insightful": 'button[aria-label*="Insightful"]',
    "Funny": 'button[aria-label*="Funny"]',
}
```

---

## n8n Workflow

### Trigger
- **Schedule:** 9am Mon-Fri EST
- **Manual:** Execute workflow button

### Flow
```
Schedule Trigger
    ↓
Generate Daily Queue (Python)
    ↓
Read State Tracker (Google Sheets)
    ↓
Filter Active Profiles
    ↓
Split In Batches (1 at a time)
    ↓
Execute Engagement (Python main.py)
    ↓
Random Wait (3-8 min)
    ↓
Noise Check (10% chance)
    ↓
[Loop to next profile]
```

### Import Workflow

1. Start n8n: `n8n start`
2. Go to http://localhost:5678
3. Import `n8n_workflow.json` from project root

---

## CLI Reference

```bash
# Setup session (one-time, repeat monthly)
python -m src.engine --setup-session

# Single profile engagement
python main.py --url "https://linkedin.com/in/username"

# Single profile dry run
python main.py --url "https://linkedin.com/in/username" --dry-run

# Process daily batch (20 profiles from queue)
python main.py --batch

# Test batch (5 profiles)
python main.py --test-batch 5

# Noise action only
python main.py --action noise

# Check rate limit status
python main.py --status

# View today's queue
python main.py --show-queue
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
# Rate limits
DAILY_LIMIT = 20
WEEKLY_LIMIT = 80
HOURLY_LIMIT = 5

# Schedule
OPERATING_START = time(9, 0)
OPERATING_END = time(18, 0)
TIMEZONE = "America/New_York"

# Delays (seconds)
MIN_DELAY = 180
MAX_DELAY = 480
NOISE_PROBABILITY = 0.10

# Smart reactions
REACTION_CONFIDENCE_THRESHOLD = 0.5
SENTENCE_TRANSFORMER_MODEL = "all-MiniLM-L6-v2"

# Browser
HEADLESS = True
VIEWPORT = (1920, 1080)
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

All errors logged with full context to `logs/engagement.log`.

---

## Maintenance

### Daily (Automated)
- n8n runs at 9am EST
- Logs written to Google Sheets
- Rate limits auto-refill

### Weekly
- Review engagement log for patterns
- Check success rate (target: >80%)
- Monitor for LinkedIn security emails

### Monthly
- **Refresh session:** `python -m src.engine --setup-session`
- Review profile coverage
- Clean logs >90 days
- Update private/deleted profiles in tracker

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

### Same profiles engaged repeatedly
1. Check State Tracker sheet is updating
2. Verify `last_engaged_date` column populated
3. Run `python main.py --show-queue` to debug priority

### LinkedIn security warning received
1. **Stop automation immediately**
2. Wait 48-72 hours
3. Reduce `DAILY_LIMIT` to 10-15
4. Increase `MIN_DELAY` to 300

---

## Development

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
# Test single profile (dry run)
python main.py --url "https://linkedin.com/in/test" --dry-run

# Test with visible browser
# Set HEADLESS = False in config/settings.py
python main.py --url "https://linkedin.com/in/test"
```

---

## Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| playwright | 1.40+ | Browser automation |
| sentence-transformers | 2.2+ | Smart reaction analysis |
| gspread | 5.12+ | Google Sheets API |
| google-auth | 2.25+ | Google authentication |
| structlog | 23.2+ | Structured logging |
| pytz | 2023.3+ | Timezone handling |
| tenacity | 8.2+ | Retry logic |

---

## Team Contacts

- **Project Owner:** [Your Name]
- **Repository:** github.com/your-org/LinkedinOutreach
- **Slack:** #linkedin-automation

---

## License

Internal use only. Do not distribute.

---

**Last Updated:** February 2026
**Version:** 1.0.0