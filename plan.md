# Implementation Plan: Stochastic Scheduler & Coverage-First Rate Limiting

## 1. Problem Statement

The current system uses a **token bucket algorithm** (`src/rate_limiter.py`) for rate limiting. While functionally correct, token buckets produce uniform consumption patterns that are detectable by anti-automation systems. The priority scoring (`src/priority.py`) is recency-bonus-heavy and uses strict top-N selection, which creates predictable engagement patterns.

This plan replaces both components with a **stochastic budget allocation** system that pre-plans weekly schedules, uses coverage-first priority scoring, and produces human-like irregular engagement cadence -- all while preserving every other component in the pipeline (engagement engine, noise actions, monitoring, sheets client, post fetcher, reaction analyzer).

---

## 2. What Changes, What Doesn't

### Replaced entirely
| File | Current Role | Replacement |
|------|-------------|-------------|
| `src/rate_limiter.py` | Token bucket (Daily/Weekly/Hourly buckets, refill logic, state persistence) | `src/scheduler.py` -- stochastic budget allocator + simple counter guards |
| `src/priority.py` | Recency-bonus-weighted priority scoring + top-N selection | `src/scorer.py` -- coverage-first scoring with jitter + weighted random sampling |

### New files
| File | Purpose |
|------|---------|
| `src/scheduler.py` | Weekly plan generation, daily queue extraction, counter-based hard limits |
| `src/scorer.py` | Priority scoring (coverage-first), weighted random sampling, forced inclusion logic |
| `src/weekly_plan.py` | Data models for `WeeklyPlan`, `DailySlot`, `ScheduledEngagement` |
| `src/timing.py` | Poisson-distributed intra-day timing with time-varying rate function |
| `tests/test_scheduler_sim.py` | Monte Carlo coverage simulation (tune scoring weights) |
| `tests/test_timing_sim.py` | Timing distribution visualization/validation |
| `tests/test_scorer_sim.py` | Priority score distribution analysis, forced-inclusion validation |
| `schedule_state.json` | Persisted weekly plan (replaces `rate_limit_state.json`) |

### Untouched (no changes)
| File | Why |
|------|-----|
| `src/engagement.py` | Only calls `rate_limiter.check_limits()` and `rate_limiter.consume()` -- interface stays identical |
| `src/engine.py` | Same as above -- calls the same two methods on whatever rate limiter it gets |
| `src/post_fetcher.py` | Completely independent -- fetches posts, no scheduling awareness |
| `src/reaction_analyzer.py` | Completely independent -- analyzes content |
| `src/smart_reactions.py` | Re-export wrapper, no changes |
| `src/noise_actions.py` | Triggered by engine after engagement, no scheduling awareness |
| `src/monitoring.py` | Health scoring/circuit breaker -- consumed by engine, not by scheduler |
| `src/sheets_client.py` | Read/write layer -- scheduler calls it for state data, interface unchanged |
| `config/settings.py` | New constants added, existing ones preserved |

### Modified (minimal, interface-preserving edits)
| File | Change |
|------|--------|
| `src/__init__.py` | Update imports: `RateLimiter` now comes from `src/scheduler`, add `Scheduler` export |
| `main.py` | `--batch` now calls `scheduler.get_todays_queue()` instead of `generate_daily_queue()`. Add `--generate-week` and `--show-plan` commands |
| `config/settings.py` | Add new constants for stochastic scheduling (see Section 5) |

---

## 3. Architecture Overview

```
Monday (or first run of week):
┌──────────────────────────────────────────────────────────┐
│                  WeeklyPlanner.generate()                 │
│                                                          │
│  1. Pull 100 profiles + state from Google Sheets         │
│  2. Score all profiles (coverage-first)                  │
│  3. Sample daily budgets from TruncatedNormal            │
│     [e.g., Mon:17, Tue:11, Wed:14, Thu:8, Fri:16,       │
│      Sat:6, Sun:8] = 80 total                            │
│  4. For each day:                                        │
│     a. Force-include any profile with days_since > 12    │
│     b. Fill remaining via weighted random sample          │
│     c. Assign Poisson-distributed timestamps             │
│  5. Persist plan to schedule_state.json                  │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
Daily (n8n trigger or --batch):
┌──────────────────────────────────────────────────────────┐
│               Scheduler.get_todays_queue()               │
│                                                          │
│  1. Load weekly plan from schedule_state.json            │
│  2. Extract today's slot                                 │
│  3. Return list of (profile, scheduled_time) tuples      │
│  4. Engine processes them in scheduled_time order         │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
Per-engagement (existing flow, unchanged):
┌──────────────────────────────────────────────────────────┐
│  scheduler.check_limits()  →  bool, info                 │
│  ...existing engagement flow (fetch, analyze, react)...  │
│  scheduler.consume()                                     │
│  scheduler.mark_outcome(url, "success"|"skipped"|"fail") │
└──────────────────────────────────────────────────────────┘
```

---

## 4. Detailed Component Design

### 4.1 `src/weekly_plan.py` -- Data Models

```python
@dataclass
class ScheduledEngagement:
    linkedin_url: str
    name: str
    scheduled_time: time        # HH:MM target within the day
    priority_score: float
    days_since_last_like: float
    forced: bool                # True if force-included (days_since > 12)
    status: str                 # "pending" | "done" | "skipped" | "failed" | "already_reacted" | "no_posts"

@dataclass
class DailySlot:
    date: date
    budget: int                 # how many engagements planned for this day
    engagements: List[ScheduledEngagement]
    completed: int              # counter of actually executed
    is_burst_day: bool          # flag for audit/logging

@dataclass
class WeeklyPlan:
    week_start: date            # Monday
    week_number: int            # ISO week
    total_budget: int           # sum of all daily budgets (<=80)
    days: Dict[str, DailySlot]  # "2026-02-09" -> DailySlot
    created_at: datetime
    
    def to_json() -> dict       # serialize for persistence
    @classmethod
    def from_json(data) -> WeeklyPlan  # deserialize
    def get_today() -> Optional[DailySlot]
    def total_completed() -> int
```

**Edge case handling in the data model:**
- `ScheduledEngagement.status` tracks outcomes so the plan is a living document
- `"already_reacted"` and `"no_posts"` are terminal states -- they count against the budget (the time was spent) but don't count as successful engagements for coverage tracking
- The weekly plan stores enough info to be resumed mid-week after a crash

### 4.2 `src/scorer.py` -- Coverage-First Priority Scoring

**Replaces:** `src/priority.py`

**Key differences from current `priority.py`:**

| Aspect | Current (`priority.py`) | New (`scorer.py`) |
|--------|------------------------|-------------------|
| Primary signal | `days_since * 10 + recency_bonus(15)` | `days_since * 0.8` capped at 12 (coverage-first) |
| Recency bonus | 15 points if posted < 24h (dominates score) | Removed entirely -- post-agnostic |
| Selection method | Strict top-N then shuffle | Weighted random sample from 2x pool |
| Forced inclusion | None | Any profile with `days_since > 12` force-included (up to 5/day) |
| Jitter | `uniform(-10, 10)` on final score | `uniform(0, 5)` additive -- always positive, prevents negative scores |

```python
def calculate_priority(user_state: dict, current_time: datetime) -> float:
    """
    Coverage-first priority. No recency bonus.
    
    Score range: [0.0, 17.0]
      base:   min(days_since * 0.8, 12.0)  -- caps at ~15 days
      jitter: uniform(0.0, 5.0)
    """

def score_all_profiles(state_data: List[dict], current_time: datetime) -> List[ScoredProfile]:
    """Score and return all active profiles, sorted descending."""

def select_for_day(
    scored_profiles: List[ScoredProfile],
    budget: int,
    yesterday_urls: Set[str]     # excluded -- no consecutive likes
) -> List[ScoredProfile]:
    """
    1. Remove anyone liked yesterday
    2. Force-include profiles with days_since > 12 (up to 5)
    3. Build pool of top 2*budget profiles
    4. Weighted random sample from pool to fill remaining budget
    5. Return selected profiles (unordered -- timing assigned separately)
    """
```

**Why remove recency bonus:** The current 15-point recency bonus dominates scoring. With `days_since * 10`, a profile liked 2 days ago scores 20. A profile that posted an hour ago gets +15 just for being active. This means you overwhelmingly engage with active posters -- that's a detectable signal. Real humans browse feeds and like varied content. The new system is purely coverage-driven: who haven't we engaged with recently? This is also simpler and more predictable.

**Why weighted random over top-N:** Top-N with a shuffle still always picks the same 20 highest-scored profiles. Weighted random sampling means profile #25 in priority still has a reasonable chance of being selected on any given day, creating natural variance across days.

### 4.3 `src/timing.py` -- Poisson-Distributed Intra-Day Timing

**Purpose:** Given N engagements for a day, produce N timestamps that look like a human's LinkedIn activity pattern.

```python
def generate_daily_timestamps(
    n: int,
    operating_start: time = time(9, 0),
    operating_end: time = time(18, 0)
) -> List[time]:
    """
    Non-homogeneous Poisson process with time-varying rate:
    
    rate(t) peaks at ~11:00 AM and ~2:00 PM (lunch-break browsing),
    with lower rates at start/end of operating window.
    
    Rate function (piecewise):
      09:00-10:00  base_rate * 0.6   (morning warmup)
      10:00-12:00  base_rate * 1.3   (mid-morning peak)
      12:00-13:00  base_rate * 0.8   (lunch dip)
      13:00-15:00  base_rate * 1.2   (afternoon peak)
      15:00-17:00  base_rate * 0.7   (afternoon wind-down)
      17:00-18:00  base_rate * 0.4   (end of day)
    
    Implementation:
      - Thinning algorithm on the Poisson process
      - Generate candidate times, accept/reject based on rate(t)/max_rate
      - Add per-timestamp jitter of +/- 5 minutes
      - Sort ascending
      - Enforce minimum gap of 3 minutes between consecutive timestamps
    """
```

**Why this matters:** The current system uses n8n's "random wait 3-8 min" between engagements, which produces roughly uniform inter-arrival times. A Poisson process with time-varying rate creates natural clustering (3 likes in 20 minutes, then nothing for 2 hours, then 5 likes in an hour) which is far harder to fingerprint.

### 4.4 `src/scheduler.py` -- The Main Replacement for `rate_limiter.py`

**Critical design constraint:** The engine (`src/engagement.py` and `src/engine.py`) currently calls:
```python
can_proceed, info = self.rate_limiter.check_limits()
# ... do engagement ...
self.rate_limiter.consume()
```

The new `Scheduler` class **must expose the exact same interface** so neither engine file needs structural changes.

```python
class Scheduler:
    """
    Replaces RateLimiter. Exposes same interface:
      - check_limits() -> Tuple[bool, str]
      - consume(amount=1)
      - status() -> dict
    
    Plus new capabilities:
      - generate_weekly_plan()
      - get_todays_queue() -> List[ScheduledEngagement]
      - mark_outcome(url, status)
    """
    
    def __init__(self):
        self.state_file = settings.SCHEDULE_STATE_FILE
        self.plan: Optional[WeeklyPlan] = None
        
        # Simple counters as hard guardrails (NOT token buckets)
        self.daily_count = 0
        self.weekly_count = 0
        self.hourly_count = 0
        self.hourly_reset_time = datetime.now()
        self.daily_reset_date = date.today()
        
        self._load_state()
    
    # ── Interface-compatible methods (drop-in for RateLimiter) ──
    
    def check_limits(self) -> Tuple[bool, str]:
        """
        Simple counter checks. No bucket refill math.
        Just: if count < limit, allow. Reset on boundary crossing.
        """
        self._maybe_reset_counters()
        
        if self.hourly_count >= settings.HOURLY_LIMIT:
            return False, f"hourly_limit ({self.hourly_count}/{settings.HOURLY_LIMIT})"
        if self.daily_count >= settings.DAILY_LIMIT:
            return False, f"daily_limit ({self.daily_count}/{settings.DAILY_LIMIT})"
        if self.weekly_count >= settings.WEEKLY_LIMIT:
            return False, f"weekly_limit ({self.weekly_count}/{settings.WEEKLY_LIMIT})"
        return True, "ok"
    
    def consume(self, amount: int = 1):
        """Increment counters + persist state."""
        self.daily_count += amount
        self.weekly_count += amount
        self.hourly_count += amount
        self._save_state()
    
    def status(self) -> dict:
        """Same shape as old RateLimiter.status()"""
        return {
            "daily": {"used": self.daily_count, "limit": settings.DAILY_LIMIT},
            "weekly": {"used": self.weekly_count, "limit": settings.WEEKLY_LIMIT},
            "hourly": {"used": self.hourly_count, "limit": settings.HOURLY_LIMIT},
            "plan_exists": self.plan is not None,
            "plan_week": self.plan.week_number if self.plan else None,
        }
    
    # ── New scheduling methods ──
    
    def generate_weekly_plan(self, state_data: List[dict]) -> WeeklyPlan:
        """
        Called once per week (Monday, or on first run).
        
        Steps:
          1. Score all profiles via scorer.score_all_profiles()
          2. Sample 7 daily budgets from TruncatedNormal(mean=12, std=4, min=5, max=20)
             - Adjust so sum == 80 (or <= 80)
             - Mark ~1 day as burst day (budget 18-20), ~1 day as light day (5-8)
          3. For each day, call scorer.select_for_day() with that day's budget
             - Pass previous day's selections as yesterday_urls
          4. For each day, call timing.generate_daily_timestamps() for time slots
          5. Assemble WeeklyPlan, persist to schedule_state.json
        """
    
    def get_todays_queue(self) -> List[ScheduledEngagement]:
        """
        Load plan, extract today's DailySlot, return pending engagements
        sorted by scheduled_time.
        
        If no plan exists or plan is from a previous week: auto-generate.
        """
    
    def mark_outcome(self, linkedin_url: str, outcome: str):
        """
        Update a ScheduledEngagement's status in the persisted plan.
        Handles: "done", "skipped", "failed", "already_reacted", "no_posts"
        
        For "already_reacted" and "no_posts":
          - Still counts as a schedule slot consumed (time was spent)
          - Does NOT consume a rate limit counter (no action taken on LinkedIn)
          - Coverage tracker treats this as "attempted" -- resets days_since 
            only for "done", NOT for "already_reacted"/"no_posts"
        """
    
    # ── Internal ──
    
    def _maybe_reset_counters(self):
        """Reset hourly/daily/weekly counters on boundary crossing. Simple datetime checks."""
    
    def _sample_daily_budgets(self) -> List[int]:
        """
        Sample 7 values from TruncatedNormal, adjust to sum to target (<=80).
        
        Algorithm:
          1. Draw 7 samples: clip(normal(mean=12, std=4), min=5, max=20)
          2. Compute sum. If sum > 80, scale down proportionally and re-clip.
          3. If sum < 70, scale up proportionally and re-clip.
          4. Final adjustment: add/subtract 1 from random days to hit target exactly.
          5. One random day gets +3 bump (burst), one gets -3 (light).
        """
    
    def _load_state(self):
        """Load plan + counters from schedule_state.json"""
    
    def _save_state(self):
        """Persist plan + counters to schedule_state.json"""
```

**On `already_reacted` and `no_posts` handling:**

This is where the current system has a gap. Right now, `engagement.py` returns early with an error result but the rate limiter has already been checked (though `consume()` is only called on success). The new system makes this explicit:

```
Engagement attempt on Profile X:
  ├─ Post found, reaction performed     → mark_outcome("done"),     consume()
  ├─ Post found, already reacted        → mark_outcome("already_reacted"), NO consume
  ├─ No posts found                     → mark_outcome("no_posts"),  NO consume
  └─ Error/failure                      → mark_outcome("failed"),    NO consume

Coverage implications:
  - "done"            → reset days_since_last_like for this profile
  - "already_reacted" → do NOT reset (we didn't do anything new)
  - "no_posts"        → do NOT reset (nothing to engage with)
  - "failed"          → do NOT reset
```

The scheduler's daily slot still considers these attempted -- the time/slot is used up. But the profile's coverage clock keeps ticking, meaning it'll get higher priority next time.

### 4.5 `config/settings.py` -- New Constants

```python
# ── Stochastic Scheduler ──
SCHEDULE_STATE_FILE = BASE_DIR / "schedule_state.json"

# Budget sampling
WEEKLY_BUDGET_TARGET = 80
DAILY_BUDGET_MEAN = 12
DAILY_BUDGET_STD = 4
DAILY_BUDGET_MIN = 5
DAILY_BUDGET_MAX = 20

# Coverage thresholds
FORCE_INCLUDE_DAYS_THRESHOLD = 12   # force-include if days_since > this
FORCE_INCLUDE_MAX_PER_DAY = 5       # cap forced inclusions per day
COVERAGE_GUARANTEE_DAYS = 14        # target: every profile within this window

# Scoring
PRIORITY_DAYS_WEIGHT = 0.8
PRIORITY_DAYS_CAP = 12.0
PRIORITY_JITTER_MAX = 5.0
SELECTION_POOL_MULTIPLIER = 2       # pool = budget * this

# Timing
TIMING_RATE_MORNING_WARMUP = 0.6
TIMING_RATE_MID_MORNING = 1.3
TIMING_RATE_LUNCH_DIP = 0.8
TIMING_RATE_AFTERNOON_PEAK = 1.2
TIMING_RATE_AFTERNOON_WIND = 0.7
TIMING_RATE_END_OF_DAY = 0.4
TIMING_MIN_GAP_MINUTES = 3
TIMING_JITTER_MINUTES = 5

# Burst days
BURST_DAY_PROBABILITY = 0.15        # ~1/week
BURST_DAY_EXTRA_MIN = 3
BURST_DAY_EXTRA_MAX = 5
```

---

## 5. Integration Points -- Minimal Engine Changes

### 5.1 `src/engagement.py` changes

```python
# BEFORE
from src.rate_limiter import RateLimiter

class LinkedInEngagement:
    def __init__(self):
        self.rate_limiter = RateLimiter()

# AFTER
from src.scheduler import Scheduler

class LinkedInEngagement:
    def __init__(self):
        self.rate_limiter = Scheduler()  # same variable name, same interface
```

That's it. `check_limits()` and `consume()` have identical signatures. The engine never knows the difference.

Additionally, after the engagement result is determined, add one call:

```python
# After determining result, before returning:
if hasattr(self.rate_limiter, 'mark_outcome'):
    outcome_map = {
        "success": "done",
        "already_reacted": "already_reacted",
        "no_posts": "no_posts",
    }
    outcome = outcome_map.get(result.error_code if not result.success else "success", "failed")
    self.rate_limiter.mark_outcome(profile_url, outcome)
```

Same pattern applies to `src/engine.py`.

### 5.2 `main.py` changes

```python
# Add new CLI commands
parser.add_argument("--generate-week", action="store_true", help="Generate weekly plan")
parser.add_argument("--show-plan", action="store_true", help="Show current weekly plan")
parser.add_argument("--batch", action="store_true", help="Run today's scheduled queue")

# --batch implementation changes from:
#   queue = generate_daily_queue()[:20]
# to:
#   scheduler = Scheduler()
#   queue = scheduler.get_todays_queue()
#   for engagement in queue:
#       await engage_profile(engagement.linkedin_url, engagement.name)
#       wait_until(engagement.scheduled_time)  # or delay if past scheduled time
```

### 5.3 `src/__init__.py` changes

```python
from .scheduler import Scheduler
from .scheduler import Scheduler as RateLimiter  # backward compat alias
```

---

## 6. State Persistence Schema

### `schedule_state.json` (replaces `rate_limit_state.json`)

```json
{
  "counters": {
    "daily_count": 7,
    "weekly_count": 34,
    "hourly_count": 2,
    "hourly_reset_time": "2026-02-09T14:00:00",
    "daily_reset_date": "2026-02-09",
    "weekly_reset_date": "2026-02-09"
  },
  "plan": {
    "week_start": "2026-02-09",
    "week_number": 7,
    "total_budget": 78,
    "created_at": "2026-02-09T09:01:23",
    "days": {
      "2026-02-09": {
        "budget": 17,
        "is_burst_day": false,
        "completed": 17,
        "engagements": [
          {
            "linkedin_url": "https://linkedin.com/in/someone",
            "name": "Someone",
            "scheduled_time": "09:23",
            "priority_score": 14.2,
            "days_since_last_like": 11.3,
            "forced": false,
            "status": "done"
          }
        ]
      },
      "2026-02-10": {
        "budget": 11,
        "is_burst_day": false,
        "completed": 0,
        "engagements": [
          {
            "linkedin_url": "...",
            "status": "pending"
          }
        ]
      }
    }
  },
  "saved_at": "2026-02-09T16:42:00"
}
```

---

## 7. Simulation / Testing Design

Three simulation files, each runnable standalone. No pytest dependency required, but compatible with it.

### 7.1 `tests/test_scheduler_sim.py` -- Coverage Monte Carlo

**Purpose:** Validate that 100% of profiles get engaged within 14 days under various conditions.

```
Simulates W weeks of operation:
  - 100 profiles, 80 engagements/week
  - Each week: generate plan, execute day by day
  - Track per-profile days_since_last_like
  - Inject failures: 10% of engagements randomly fail
  - Inject already_reacted: 5% of profiles already reacted
  - Inject no_posts: 5% of profiles have no posts

Output:
  - Coverage histogram: % of profiles engaged within [7, 10, 12, 14, 16] days
  - Worst-case gap (max days any profile waited)
  - Per-week engagement distribution (how many per day)
  - Forced inclusion frequency (how often the safety net triggers)

Tunable parameters exposed as CLI args:
  --weeks N             Simulation duration (default 12)
  --failure-rate F      Random failure probability (default 0.10)
  --already-reacted F   Probability profile's post is already liked (default 0.05)
  --no-posts-rate F     Probability profile has no posts (default 0.05)
  --runs N              Monte Carlo iterations (default 50)
```

### 7.2 `tests/test_scorer_sim.py` -- Priority Score Analysis

**Purpose:** Visualize and validate priority score distributions, selection fairness.

```
Given 100 synthetic profiles with varied days_since_last_like:
  - Compute priority scores 1000 times (re-rolling jitter each time)
  - Analyze: which profiles get selected most/least often?
  - Validate: does forced inclusion actually catch stragglers?
  - Compare: old formula vs new formula selection distributions

Output (printed tables, no external deps):
  - Selection frequency per profile across 1000 runs
  - Mean/std/min/max priority scores per days_since bucket
  - Forced inclusion trigger rate
```

### 7.3 `tests/test_timing_sim.py` -- Timing Distribution Validation

**Purpose:** Verify that generated timestamps look human-like.

```
Generate 1000 daily timestamp sets (each with 10-20 timestamps):
  - Plot inter-arrival time distribution (should NOT be uniform)
  - Verify minimum gap enforcement
  - Verify operating hours compliance
  - Show hourly density (should peak mid-morning and early afternoon)

Output (printed histogram, no matplotlib needed):
  - ASCII histogram of timestamps by hour
  - Inter-arrival time statistics
  - Minimum gap violations (should be 0)
```

### 7.4 Running simulations

```bash
# Full coverage simulation
python -m tests.test_scheduler_sim --weeks 12 --runs 50

# Quick sanity check
python -m tests.test_scheduler_sim --weeks 4 --runs 5

# Score distribution analysis
python -m tests.test_scorer_sim

# Timing validation
python -m tests.test_timing_sim
```

---

## 8. Implementation Order

Strict dependency order. Each phase is independently testable.

### Phase 1: Data Models + Scoring (no integration yet)
1. `src/weekly_plan.py` -- pure dataclasses, JSON serialization
2. `src/scorer.py` -- priority calculation + weighted selection
3. `tests/test_scorer_sim.py` -- validate scoring in isolation

### Phase 2: Timing
4. `src/timing.py` -- Poisson timestamp generation
5. `tests/test_timing_sim.py` -- validate timing in isolation

### Phase 3: Scheduler Core
6. `src/scheduler.py` -- weekly plan generation, counter guards, state persistence
7. `tests/test_scheduler_sim.py` -- full coverage simulation (uses scorer + timing)

### Phase 4: Integration
8. `config/settings.py` -- add new constants
9. `src/__init__.py` -- update exports
10. `src/engagement.py` -- swap `RateLimiter` for `Scheduler`, add `mark_outcome` call
11. `src/engine.py` -- same swap + mark_outcome
12. `main.py` -- add `--generate-week`, `--show-plan`, update `--batch`
13. Delete `src/rate_limiter.py` and `src/priority.py` (or move to `deprecated/`)
14. Delete `rate_limit_state.json` from `.gitignore` references, add `schedule_state.json`

### Phase 5: Validation
15. Run `test_scheduler_sim.py` with default params -- expect 99%+ coverage within 14 days
16. Dry-run `python main.py --generate-week` against real Google Sheets data
17. Dry-run `python main.py --batch --dry-run` to verify end-to-end flow
18. One live test with `--test-batch 3` on real LinkedIn

---

## 9. Risk Assessment & Rollback

| Risk | Mitigation |
|------|-----------|
| Weekly plan generation fails mid-week | Scheduler auto-regenerates if plan is stale/missing. Counter guards still enforce hard limits independently. |
| Counter state corrupted | Counters reset on boundary crossing anyway. Worst case: one extra engagement before next reset. |
| Profile state in Sheets desyncs | Scheduler reads fresh state from Sheets on every plan generation. Stale plan entries just get re-scored next week. |
| New system produces worse coverage than old | Run `test_scheduler_sim.py` before deploying. If coverage < 95% at 14 days, tune `FORCE_INCLUDE_DAYS_THRESHOLD` down to 10. |
| Need to rollback | Revert `engagement.py` and `engine.py` imports back to `from src.rate_limiter import RateLimiter`. The old files are untouched until Phase 4 step 13. |

---

## 10. Key Design Decisions & Rationale

**Q: Why not keep token buckets as the guard and layer scheduling on top?**
A: Token buckets add conceptual overhead (refill rates, token counts, last_refill timestamps) for something that's just "did we hit 20 today?". Simple counters with reset-on-boundary are equivalent for fixed-window limits and much easier to reason about. The scheduling layer handles the interesting behavior.

**Q: Why pre-plan the whole week instead of deciding daily?**
A: A weekly plan allows us to guarantee budget distribution across days (no accidentally spending 60 by Wednesday), guarantee coverage (every profile assigned at least once per 2-week window), and inspect the plan before execution. Daily planning is reactive; weekly planning is proactive.

**Q: Why Poisson timing instead of uniform random delays?**
A: Uniform delays between engagements produce a suspiciously regular cadence. Poisson processes naturally model "events occurring at random times" and are the standard model for human arrival patterns. The time-varying rate function adds the observation that humans are more active at certain hours.

**Q: Why remove recency bonus entirely?**
A: Covered in Section 4.2. The recency bonus created a feedback loop where active posters get most of the attention, which is both detectable and defeats the coverage goal. The whole point is to engage all 100 profiles, not just the ones who post frequently.

**Q: How does this interact with noise actions?**
A: It doesn't, by design. Noise actions are triggered by the engine at 10% probability after each engagement. The scheduler doesn't know about them, the engine decides independently. The timing layer's Poisson gaps already incorporate natural idle periods where noise actions fit organically.