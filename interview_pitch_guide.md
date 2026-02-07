# Technical Deep Dive: Autonomous LinkedIn Engagement Agent

This guide provides a granular explanation of the algorithms, logic, and data flow within the project. It is intended for a technical deep-dive interview where you need to explain *exactly* how the system works.

---

## 1. Core Algorithms (The "Math" Behind the Bot)

### A. Priority Scoring Logic (`src/scorer.py`)
The goal isn't just to engage effectively, but to maintain **coverage** across the entire network while avoiding predictable patterns.

*   **Formula:** `Score = Base + Jitter`
    *   **Base:** `min(days_since_last_engagement * 0.8, 12.0)`
        *   *Logic:* The longer we ignore a profile, the higher its score, up to a cap (12.0). This ensures "stale" profiles drift to the top.
    *   **Jitter:** `random.uniform(0.0, 5.0)`
        *   *Logic:* Adds entropy. Two profiles last liked 10 days ago won't always be picked in the same order. This breaks "bot fingerprints."

### B. Daily Selection Logic (`src/scorer.py`)
Once scored, how do we pick the ~15 people for today? We use a **Weighted Random Sampling** strategy with constraints:

1.  **Filter Yesterday:** `if profile in yesterday_urls: SKIP` (Prevents back-to-back spamming).
2.  **Forced Inclusion:** If `days_since > 12`, automatically force into the daily batch (up to 5 max).
3.  **Weighted Choice:**
    *   Pool size: Top `2 * budget` profiles (e.g., top 30 candidates for 15 slots).
    *   Probability: `P(select) = Score / Total_Score`.
    *   *Result:* High-score profiles are *likely* to be picked, but not *guaranteed*.

### C. Temporal Scheduling: Poisson Process (`src/timing.py`)
We do **not** use `cron` to schedule individual likes (e.g., "every 5 mins"). That is highly detectable.
Instead, we use a **Non-Homogeneous Poisson Process** via "Thinning":

1.  **Rate Function `λ(t)`:** Defined activity levels throughout the day:
    *   09:00 - 10:00: Warmup (Rate: 0.6)
    *   10:00 - 12:00: **Mid-Morning Peak** (Rate: 1.3)
    *   12:00 - 13:00: **Lunch Dip** (Rate: 0.8)
    *   13:00 - 15:00: Afternoon Peak (Rate: 1.2)
    *   17:00 - 18:00: Cooldown (Rate: 0.4)
2.  **Algorithm (Rejection Sampling):**
    *   Generate a uniform random time `t`.
    *   Calculate acceptance probability `P = λ(t) / λ_max`.
    *   Roll dice. If `random() < P`, keep `t`. Else, discard.
    *   *Result:* Activities cluster naturally around peaks and thin out during lunch/evening, just like a human.

---

## 2. Engagement & Safety Logic (`src/engagement.py`)

### The "Engagement Loop"
For each target profile, the system performs a sequence of checks to ensure safety and validity:

1.  **Session Validation:**
    *   Before looking at the target, checks if we are logged in (`SessionValidator`).
2.  **Human Mimicry (Noise):**
    *   **Logic:** `if random() < noise_probability:` -> Run `noise_actions.py`.
    *   **Action:** might scroll the main feed, visit a random tech leader (e.g., Satya Nadella), or view a Company Page.
    *   *Why:* This dilutes the "click-stream" data LinkedIn analyzes. It hides the target access pattern.
3.  **Scraping Strategy:**
    *   Tools: `Playwright` + `BeautifulSoup`.
    *   Action: Finds the *most recent* post. If no post in 30 days -> `mark_outcome("no_posts")`.
4.  **Reaction:**
    *   Clicks "Like".
    *   Logs the exact URN (United Resource Name) to avoid re-liking the same post later.

---

## 3. Data Flow & Logging Architecture

### The "Ledger" vs. "State" Approach
We use Google Sheets as a database with two distinct schemas:

1.  **Immutable Log (`LinkedIn_Engagement_Log`):**
    *   **Type:** Append-Only Ledger.
    *   **Fields:** Timestamp, Profile URL, Action (Like/Skip), Status (Success/Fail).
    *   *Purpose:* Audit trail. Never edits old rows.
2.  **Mutable State (`LinkedIn_State_Tracker`):**
    *   **Type:** Current State Table.
    *   **Fields:** Profile URL, `last_engaged_date`, `engagement_count`, `consecutive_skips`.
    *   *Logic:* Updated *after* every successful action.
    *   *Purpose:* Input for the Scorer.

### The Orchestrator (n8n)
*   **Trigger:** Daily Schedule or Manual Webhook.
*   **Execution:** Runs `python main.py --batch`.
*   **Parsing:**
    *   Python outputs structured JSON logs to `stdout`.
    *   n8n parses this JSON. If `success_rate < 70%`, it sends a Slack alert.
    *   *Why:* Decoupling execution (Python) from alerting (n8n) makes the system more robust.

---

## 4. Key Libraries & Decisions

*   **Playwright vs Selenium:**
    *   Playwright is chosen for its **auto-waiting** mechanism (reduces flakes on dynamic React apps like LinkedIn) and efficient `BrowserContext` for session storage (cookies).
*   **Structlog:**
    *   Used for JSON-structured logging. Makes parsing logs in n8n/Splunk/ELK trivial.
*   **Gspread:**
    *   Lightweight wrapper for Google Sheets API. We use `batch_update` where possible to avoid hitting API rate limits.
