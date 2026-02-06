# n8n Implementation Guide (LinkedIn Outreach Automation)

This guide explains how to run the entire project through an n8n workflow using the **existing Python files** in this repo.

It covers:
- **One-time setup** on the machine where n8n runs
- **Exact n8n nodes required**
- **How to connect nodes**
- **What each node runs** (Python commands and expected behavior)

---

## Assumptions

- You run n8n on the same machine (or container) that can execute this repo’s Python environment.
- You already configured Google Sheets API and the service account key exists at `config/credentials.json`.
- You will run **one daily workflow** that:
  - (Optionally) generates a **weekly plan** once a week
  - Executes today’s schedule via `python main.py --batch`
- Your LinkedIn session/cookies exist on disk (see below).

---

## One-time setup (outside n8n)

### 1) Confirm required files exist (and are not committed)

The automation depends on these local files:
- `config/credentials.json` (Google service account key)
- `linkedin_session.json` (LinkedIn browser session used by `src/engine.py`)  
  - Created by `python -m src.engine --setup-session`
- OR `linkedin_cookies.json` (cookie-based session used by `src/engagement.py`)  
  - Only relevant if you run the `LinkedInEngagement` path; the n8n workflow in this guide uses `main.py` which calls `LinkedInEngagement`, so cookies must exist for that path.

Notes:
- Your `.gitignore` already excludes these.
- n8n must have filesystem access to them.

### 2) Create and install Python environment

From the repo root:

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

If you use the `linkedin_scraper/` package features, also install it editable:

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project/linkedin_scraper"
pip install -e .
```

### 3) Verify commands work manually

Run these once from terminal to confirm your environment:

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project"
source .venv/bin/activate
python main.py --status
python main.py --generate-week
python main.py --show-plan
python main.py --batch --dry-run
```

If `--generate-week` fails:
- It usually means the Sheets names in `config/settings.py` do not match the spreadsheet titles, or service account access is missing.

### 4) Decide how n8n will run Python

You have two common options:

**Option A (recommended): n8n “Execute Command” node**
- Run a shell command that activates `.venv` and runs `python main.py ...`.

**Option B: n8n “Execute Python” node**
- Only works if your n8n has that node installed/enabled and points to the same Python environment.
- This guide uses **Option A** because it’s universal and predictable.

---

## What the workflow does (high level)

Daily at 9am (Mon–Fri), the workflow will:

1. Ensure Sheets state tracker is initialized (this happens inside your code).
2. On Mondays (or when there is no plan), generate a weekly plan:
   - `python main.py --generate-week`
3. Run today’s queue:
   - `python main.py --batch`
4. Optionally send a notification if the batch fails.

Your Python code already:
- Loads Sheets using `config/credentials.json`
- Generates and persists the weekly plan to `schedule_state.json`
- Loads today’s scheduled queue and runs it
- Uses logging via `structlog` and prints JSON results per profile

---

## n8n workflow: required nodes and connections

### Node list (minimum viable workflow)

1. **Cron** (Schedule Trigger)
2. **IF** (Is Monday?)
3. **Execute Command** (Generate weekly plan)
4. **Execute Command** (Run today’s batch)
5. **Execute Command** (Show status) (optional but recommended)
6. **Slack / Email / Discord** (Notify on failure) (optional)

### Connection diagram (logical)

```
Cron
  ↓
Execute Command (Status)   [optional, but good for logs]
  ↓
IF (Is Monday?)
  ├─ true  → Execute Command (Generate Week) → Execute Command (Run Batch)
  └─ false → Execute Command (Run Batch)
                         ↓
               Notify on Failure (optional)
```

---

## Step-by-step: build the workflow in n8n

### Step 1) Create a new workflow

- Name: `LinkedIn Outreach - Daily Scheduler`

### Step 2) Add node: Cron (Schedule Trigger)

**Node:** `Cron`

**Configuration (example):**
- Mode: “Every Weekday”
- Time: `09:00`
- Timezone: `America/New_York`

Output of this node is just a trigger signal.

### Step 3) Add node: Execute Command (Status) (recommended)

**Node:** `Execute Command`

**Name:** `Status`

**Command (macOS zsh example):**

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && \
source ".venv/bin/activate" && \
python main.py --status
```

**Connect:** `Cron` → `Status`

Why this node helps:
- Confirms the scheduler state file can be read
- Prints current counters and plan presence into n8n logs

### Step 4) Add node: IF (Is Monday?)

**Node:** `IF`

**Name:** `Is Monday`

**Condition:** Use n8n expression to check weekday.

Example expression (Date & Time):
- Left value (Expression):
  - `{{ $now.setZone('America/New_York').weekday }}`
- Operation: `equals`
- Right value: `1`

In Luxon (used by n8n), weekday is:
- 1 = Monday
- 7 = Sunday

**Connect:** `Status` → `Is Monday`

### Step 5) Add node: Execute Command (Generate weekly plan)

**Node:** `Execute Command`

**Name:** `Generate Week`

**Command:**

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && \
source ".venv/bin/activate" && \
python main.py --generate-week
```

**Connect:** `Is Monday (true)` → `Generate Week`

Notes:
- This reads Sheets, merges names, and writes `schedule_state.json`.

### Step 6) Add node: Execute Command (Run today’s batch)

**Node:** `Execute Command`

**Name:** `Run Batch`

**Command (live mode):**

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && \
source ".venv/bin/activate" && \
python main.py --batch
```

**Command (safe dry-run test):**

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && \
source ".venv/bin/activate" && \
python main.py --batch --dry-run
```

**Connect both paths:**
- `Generate Week` → `Run Batch`
- `Is Monday (false)` → `Run Batch`

What happens here:
- `Scheduler.get_todays_queue()` loads (or generates) the plan and returns pending engagements for today.
- The batch runs each profile sequentially.
- Between profiles, it sleeps using your `settings.get_random_delay()` (unless `--dry-run`).

### Step 7) Add node: Notify on Failure (optional but recommended)

Pick one:
- **Slack node**
- **Email node**
- **Discord node**

**Connect:** `Run Batch` → `Notify on Failure`

Configure the notify node to only send on failure:
- In n8n, you can use:
  - “Continue On Fail” disabled (so node errors stop the workflow)
  - Add an **Error Trigger** workflow (recommended), or
  - Use an IF node after `Run Batch` checking for non-empty stderr/exit code (varies by node version)

**Recommended approach:** create a second workflow:
- Trigger: **Error Trigger**
- Filter: workflow name contains `LinkedIn Outreach - Daily Scheduler`
- Action: send Slack/Email with the error details

---

## Optional: separate weekly plan generation workflow

If you want the plan generation isolated from the daily run:

### Workflow A: Weekly Plan Generator
Nodes:
1. Cron (Every Monday 08:55)
2. Execute Command (Generate Week)
3. Execute Command (Show Plan)

Commands:

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && \
source ".venv/bin/activate" && \
python main.py --generate-week
```

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project" && \
source ".venv/bin/activate" && \
python main.py --show-plan
```

### Workflow B: Daily Batch Runner
Nodes:
1. Cron (Mon–Fri 09:00)
2. Execute Command (Run Batch)

---

## Operational notes

### Where logs go
- n8n stores node logs (stdout/stderr).
- Your Python also logs via `structlog` (JSON lines) into stdout.
- File log path is `logs/engagement.log` for some components; ensure that directory exists and is writable by the n8n runtime user.

### Permissions and file access
If n8n runs as a different user (service account / docker user), ensure it can read:
- `config/credentials.json`
- `linkedin_session.json` or `linkedin_cookies.json`
and can write:
- `schedule_state.json`
- `logs/`

### First live run checklist
1. Run `python main.py --generate-week`
2. Run `python main.py --show-plan`
3. Run `python main.py --batch --dry-run`
4. Run `python main.py --batch` with a very small test batch:
   - Use `python main.py --test-batch 3` (this limits the batch runner)

---

## Troubleshooting

### “Sheets connection failed”
- Confirm the spreadsheet titles match:
  - `settings.INPUT_SHEET_NAME`
  - `settings.LOG_SHEET_NAME`
  - `settings.STATE_TRACKER_SHEET_NAME`
- Confirm the service account email has access to those sheets.

### “Session file not found” / authentication failures
- If using `src/engine.py` session-based flow:
  - Run: `python -m src.engine --setup-session`
  - Confirm `linkedin_session.json` exists
- If using cookie-based `LinkedInEngagement` flow:
  - Ensure `linkedin_cookies.json` exists and is valid

### “No engagements scheduled for today”
- Run `python main.py --show-plan`
- If no plan exists, run `python main.py --generate-week`

