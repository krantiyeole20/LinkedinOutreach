# CREATION.md -- n8n Workflow Setup Guide

> For: `linkedin_outreach_workflow.json`
> Audience: Someone who has never touched n8n before
> Time to complete: ~45 minutes

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Install & Start n8n](#2-install--start-n8n)
3. [Import the Workflow](#3-import-the-workflow)
4. [Critical: Enable Execute Command Node](#4-critical-enable-execute-command-node)
5. [Configure Each Node](#5-configure-each-node)
6. [Set Workflow Timezone](#6-set-workflow-timezone)
7. [Test the Workflow](#7-test-the-workflow)
8. [Go Live](#8-go-live)
9. [Node Reference Table](#9-node-reference-table)
10. [Troubleshooting](#10-troubleshooting)

---

## 1. Prerequisites

### On your machine (before opening n8n)

| Requirement | How to verify | How to fix |
|---|---|---|
| Node.js 18+ | `node --version` | [nodejs.org](https://nodejs.org) |
| Python 3.10+ | `/opt/anaconda3/bin/python3 --version` | Install Anaconda/Miniconda |
| This repo cloned | `ls ~/Documents/Linkedin\ Automation\ Project/main.py` | Clone the repo |
| Google Sheets credentials | `ls config/credentials.json` | Create service account in GCP console |
| LinkedIn cookies/session file | `ls linkedin_cookies.json` OR `ls linkedin_session.json` | Run `python -m src.engine --setup-session` |
| Playwright chromium installed | `python -c "from playwright.sync_api import sync_playwright"` | `playwright install chromium` |
| 3 Google Sheets created & shared with service account | Check Sheets UI | See README.md for sheet names |

### Python environment setup

Since you are using Anaconda, you don't need a venv. Just ensure dependencies are installed:

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project"
/opt/anaconda3/bin/pip install -r requirements.txt
/opt/anaconda3/bin/playwright install chromium
```

### Verify Python commands work

```bash
cd "/Users/krantiy/Documents/Linkedin Automation Project"
/opt/anaconda3/bin/python3 main.py --status
/opt/anaconda3/bin/python3 main.py --generate-week
/opt/anaconda3/bin/python3 main.py --show-plan
/opt/anaconda3/bin/python3 main.py --batch --dry-run
```

If all four commands run without crashing, you're good to proceed.

---

## 2. Install & Start n8n

### Option A: npm (recommended for local dev)

```bash
npm install -g n8n

# Start with Execute Command node enabled (CRITICAL)
N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand n8n start
```

### Option B: Docker

```bash
docker run -it --rm \
  --name n8n \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  -v "/Users/krantiy/Documents/Linkedin Automation Project":"/Users/krantiy/Documents/Linkedin Automation Project" \
  -e N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand \
  n8nio/n8n
```

The volume mount (`-v`) gives the n8n container access to your project directory. Without it, Execute Command nodes can't find your Python files.

### Open n8n

Go to `http://localhost:5678` in your browser. First time: create an account (local only, no cloud needed).

---

## 3. Import the Workflow

**CRITICAL: You must enable Execute Command BEFORE importing. If you already imported and the commands are empty, see Troubleshooting Section 10.**

1. In n8n, click the **three dots (...)** in the top-right corner
2. Click **Import from File**
3. Select `n8n/LinkedIn Outreach.json`
4. You should see 13 nodes appear on the canvas

**Verify the import worked correctly:**
- Double-click node **#3 "Health Check"**
- Check if the "Command" field has content starting with `cd "/Users/krantiy/..."`
- If the Command field is **EMPTY**, see [Section 10: Troubleshooting](#10-troubleshooting) → "Execute Command nodes have empty Command fields"

---

## 4. Critical: Enable Execute Command Node

**n8n v2.0+ disables the Execute Command node by default for security reasons.** If you see errors about "Unrecognized node type: n8n-nodes-base.executeCommand", this is why.

### Fix: Set environment variable before starting n8n

**npm install:**
```bash
N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand n8n start
```

**Docker:**
Add `-e N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand` to your docker run command.

**Docker Compose:**
```yaml
environment:
  - N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand
```

**Systemd service:**
Add to your n8n .env file:
```
N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand
```

After setting this, **restart n8n completely**. The Execute Command nodes should now show without errors.

---

## 5. Configure Each Node

After importing, most nodes are ready to go. Below is every node, what it does, and what (if anything) you need to change.

### Legend

- **NO CHANGES NEEDED** = Works out of the box after import
- **VERIFY PATH** = Check that the project directory path matches your machine
- **CONFIGURE** = You must edit something before first run

---

### Node 1: Daily 9am EST (Schedule Trigger)

**What it does:** Fires the workflow every day at 9:00 AM Eastern Time.

**After import, check:**
1. Double-click the node to open it
2. You should see: Trigger Interval = Cron Expression, Expression = `0 9 * * *`
3. This means "minute 0, hour 9, every day, every month, every weekday"

**To change the time:** Edit the cron expression.
- `0 10 * * *` = 10am daily
- `30 8 * * *` = 8:30am daily
- `0 9 * * 1-5` = 9am weekdays only

**Status: NO CHANGES NEEDED** (unless you want a different time)

---

### Node 2: Manual Trigger

**What it does:** Lets you run the workflow on-demand by clicking "Test Workflow" in the n8n UI. Useful for debugging.

**After import:** Nothing to configure. Just know it exists.

**How to use it:** Click the "Test Workflow" button (play icon) in the top-right of the canvas. The workflow will run from this trigger instead of waiting for the schedule.

**Status: NO CHANGES NEEDED**

---

### Node 3: Health Check (Execute Command)

**What it does:** Checks the circuit breaker health score from `src/monitoring.py`. If score is below 50, the command exits with code 1, which stops the entire workflow.

**After import, verify:**
1. Double-click the node
2. In the Command field, verify the path starts with:
   ```
   cd "/Users/krantiy/Documents/Linkedin Automation Project"
   ```
3. If your repo is in a different location, update this path

**How it works in n8n:** When a node exits with a non-zero code and "Continue On Fail" is disabled, the workflow stops. This is intentional -- if the circuit breaker is open, we don't want to engage.

**To enable "Continue On Fail" (optional):**
If you want the workflow to continue even when health is low (not recommended), click Settings (gear icon) in the node and toggle "Continue On Fail" to true.

**Status: VERIFY PATH**

---

### Node 4: Load Status (Execute Command)

**What it does:** Runs `python main.py --status` to print current rate limit counters and whether a weekly plan exists.

**After import, verify:**
1. Double-click the node
2. Verify the `cd` path matches your project directory

**The output of this node is used downstream** by the "Plan Exists?" node to decide whether to regenerate the weekly plan.

**Status: VERIFY PATH**

---

### Node 5: Is Monday? (IF Node)

**What it does:** Checks if today is Monday. Two branches:
- **True (top output):** Goes to Generate Weekly Plan
- **False (bottom output):** Goes to Plan Exists? check

**After import, check:**
1. Double-click the node
2. Condition should read: `{{ $now.setZone('America/New_York').weekday }}` equals `1`
3. In n8n's Luxon library: 1 = Monday, 7 = Sunday

**How IF nodes work in n8n:** IF nodes always have exactly 2 outputs. The top connector = condition is true. The bottom connector = condition is false. You can see this labeled as "true" and "false" when you hover over the output dots.

**Status: NO CHANGES NEEDED**

---

### Node 6: Generate Weekly Plan (Execute Command)

**What it does:** Runs `python main.py --generate-week` which:
- Reads 100 profiles from Google Sheets
- Scores them with coverage-first algorithm
- Samples 7 stochastic daily budgets (sum <= 80)
- Assigns Poisson-distributed timestamps
- Writes `schedule_state.json`

**Only runs on Mondays** (gated by the Is Monday? node).

**After import, verify:**
1. Double-click, verify the `cd` path

**Status: VERIFY PATH**

---

### Node 7: Show Plan (Audit Log) (Execute Command)

**What it does:** Runs `python main.py --show-plan` and prints the full weekly schedule to the n8n execution log. Purely for audit/debugging.

**After import, verify:** Path only.

**How to view its output after a run:** Click the node after execution. The right panel shows "Output" with stdout content.

**Status: VERIFY PATH**

---

### Node 8: Plan Exists? (IF Node)

**What it does:** On Tue-Sun, checks whether the Load Status output contains `plan_exists`. If the weekly plan file is missing or corrupt, it routes to the recovery branch.

**After import, check:**
1. Double-click the node
2. Condition: `{{ $('Load Status').item.json.stdout }}` contains `plan_exists`

**Two branches:**
- **True (top):** Plan exists, proceed to Run Batch
- **False (bottom):** Plan missing, go to Regenerate Plan

**Status: NO CHANGES NEEDED** (but verify your `--status` command actually outputs `plan_exists` when a plan is loaded)

---

### Node 9: Regenerate Plan (Recovery) (Execute Command)

**What it does:** Same as Generate Weekly Plan, but runs on Tue-Sun when the plan file is missing. Safety net.

**After import, verify:** Path only.

**Status: VERIFY PATH**

---

### Node 10: Run Batch (Execute Command)

**What it does:** The main node. Runs `python main.py --batch` which:
- Loads today's queue from `schedule_state.json`
- For each profile: fetch post, analyze content, select reaction, perform engagement
- Respects Poisson-distributed timing between engagements
- Outputs JSON lines to stdout with per-engagement results

**This node takes the longest to execute** (15-45 minutes depending on daily budget and delays).

**After import, verify:**
1. Path
2. For your first test, change the command to: `python main.py --batch --dry-run 2>&1`
3. Once satisfied, remove `--dry-run`

**Important: the `2>&1`** at the end captures stderr along with stdout. Don't remove it -- the Parse Results node needs the combined output.

**Status: VERIFY PATH + use --dry-run for first test**

---

### Node 11: Parse Results (Code Node - JavaScript)

**What it does:** Parses the stdout from Run Batch, counting how many engagements succeeded, failed, were already reacted, had no posts, etc. Outputs structured JSON metrics.

**After import:** Nothing to configure. This runs JavaScript inside n8n (not on your system).

**Output fields it produces:**
- `done`, `failed`, `skipped`, `already_reacted`, `no_posts` (counts)
- `total`, `success_rate` (aggregates)
- `has_errors` (boolean, drives the error notification branch)
- `low_success_rate` (boolean, true if < 70%)
- `engagements` (array of per-profile results)

**Status: NO CHANGES NEEDED**

---

### Node 12: Daily Report (Execute Command)

**What it does:** Takes the parsed stats and:
1. Prints a formatted daily report to the n8n log
2. Appends a summary row to the Google Sheets engagement log

**After import, verify:** Path.

**Note:** This node receives the Parse Results JSON via the command argument `'{{ JSON.stringify($json) }}'`. The Python script reads it from `sys.argv[1]`.

**Status: VERIFY PATH**

---

### Node 13: Is Sunday? (IF Node)

**What it does:** Checks if today is Sunday (weekday = 7). Routes to Weekly Summary on Sundays, to Weekday End otherwise.

**Status: NO CHANGES NEEDED**

---

### Node 14: Weekly Summary (Execute Command)

**What it does:** On Sunday, loads the full weekly plan and prints a comprehensive summary: per-day breakdown, total completed vs budget, success rates.

**After import, verify:** Path.

**Status: VERIFY PATH**

---

### Node 15: Has Errors? (IF Node)

**What it does:** Checks the `has_errors` boolean from Parse Results. If true (any failures occurred), routes to the Slack notification branch.

**After import, check:**
1. Condition: `{{ $('Parse Results').item.json.has_errors }}` equals `true`

**Status: NO CHANGES NEEDED**

---

### Node 16: Format Error Payload (Code Node - JavaScript)

**What it does:** Formats the error details into a Slack-compatible message payload with severity level, action required text, and structured fields.

**Status: NO CHANGES NEEDED**

---

### Node 17: Send Slack Alert (HTTP Request)

**What it does:** POSTs the formatted error payload to a Slack webhook URL.

**After import, CONFIGURE:**
1. Double-click the node
2. Find the URL field
3. **Replace** `https://hooks.slack.com/services/YOUR/WEBHOOK/URL` with your actual Slack webhook URL

**How to get a Slack webhook URL:**
1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Create New App > From scratch
3. Name it "LinkedIn Automation Alerts", select your workspace
4. Go to Incoming Webhooks > Activate > Add New Webhook to Workspace
5. Choose a channel (e.g., #linkedin-automation)
6. Copy the webhook URL

**If you don't use Slack:** You have several options:
- **Delete** this node and the Format Error Payload node (the workflow still works without them)
- **Replace** with an Email Send node (n8n has a built-in one -- search "Send Email" in the nodes panel)
- **Replace** with a Discord webhook (same HTTP Request structure, different URL format)

**The `onError: continueRegularOutput` setting** means if the Slack webhook fails (bad URL, Slack down), the workflow doesn't crash. It just logs the error and moves on.

**Status: CONFIGURE (replace webhook URL)**

---

### Node 18: No Errors - Done (No Operation)

**What it does:** Nothing. It's a visual endpoint for the "no errors" branch. n8n requires a node at the end of every branch -- NoOp serves as a clean termination point.

**Status: NO CHANGES NEEDED**

---

### Node 19: Weekday End (No Operation)

**What it does:** Same as above. Visual endpoint for the "not Sunday" branch.

**Status: NO CHANGES NEEDED**

---

## 6. Set Workflow Timezone

The workflow JSON includes `"timezone": "America/New_York"` in settings, but verify it imported correctly:

1. Click the **gear icon** (Settings) in the top-right of the canvas (not inside a node)
2. Look for **Timezone**
3. Confirm it says `America/New_York`
4. If blank, set it manually

This affects:
- When the Schedule Trigger fires (9am in this timezone)
- What `$now.setZone('America/New_York').weekday` returns in IF conditions

---

## 7. Test the Workflow

### Step 1: Dry run via Manual Trigger

1. First, edit the **Run Batch** node: add `--dry-run` to the command:
   ```
   ... && python main.py --batch --dry-run 2>&1
   ```
2. Click **"Test Workflow"** (play button, top-right)
3. n8n will execute from the Manual Trigger through the entire chain
4. Click on each node to see its output in the right panel

**What to look for:**
- Health Check: stdout shows `{"health_score": 100, ...}`
- Load Status: stdout shows current counters
- Is Monday?: Check which branch activated (green checkmark on the active path)
- Run Batch: stdout shows JSON lines with `DRY_RUN_Like`, `DRY_RUN_Celebrate`, etc.
- Parse Results: output shows `done: X, failed: 0, ...`

### Step 2: Small live test

1. Edit Run Batch command to use test-batch:
   ```
   ... && python main.py --test-batch 3 2>&1
   ```
2. Click "Test Workflow"
3. Check Google Sheets engagement log for 3 new rows
4. Verify no LinkedIn security warnings on your account

### Step 3: Full batch test

1. Restore Run Batch command to:
   ```
   ... && python main.py --batch 2>&1
   ```
2. Click "Test Workflow"
3. Wait 15-45 minutes for completion
4. Review Parse Results output for success/failure counts

---

## 8. Go Live

### Activate the workflow

1. In the top-right, toggle the **Inactive/Active** switch to **Active** (it turns green)
2. The Schedule Trigger is now armed -- it will fire at 9am EST daily

### What "Active" means

- n8n must be running for the trigger to fire. If you close the terminal/stop Docker, the schedule pauses.
- For production, run n8n as a background service (see below).

### Run n8n as a background process

**macOS/Linux (pm2):**
```bash
npm install -g pm2
N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand pm2 start n8n
pm2 save
pm2 startup   # auto-start on reboot
```

**Docker Compose (recommended for production):**
```yaml
version: '3'
services:
  n8n:
    image: n8nio/n8n
    restart: always
    ports:
      - "5678:5678"
    environment:
      - N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand
      - GENERIC_TIMEZONE=America/New_York
      - TZ=America/New_York
    volumes:
      - ~/.n8n:/home/node/.n8n
      - /Users/krantiy/Documents/Linkedin Automation Project:/Users/krantiy/Documents/Linkedin Automation Project
```

```bash
docker-compose up -d
```

### Monitor executions

1. In n8n sidebar, click **Executions**
2. You'll see a list of all past runs with status (success/error)
3. Click any execution to see the full node-by-node flow with data at each step

---

## 9. Node Reference Table

Quick reference of all 19 nodes, their types, and configuration status.

| # | Node Name | Type | Needs Config? | What to Check |
|---|---|---|---|---|
| 1 | Daily 9am EST | Schedule Trigger | No | Cron: `0 9 * * *` |
| 2 | Manual Trigger | Manual Trigger | No | Just click Test Workflow |
| 3 | Health Check | Execute Command | Verify path | Circuit breaker, exit(1) if unhealthy |
| 4 | Load Status | Execute Command | Verify path | `--status` output |
| 5 | Is Monday? | IF | No | Weekday == 1 |
| 6 | Generate Weekly Plan | Execute Command | Verify path | `--generate-week`, Monday only |
| 7 | Show Plan (Audit Log) | Execute Command | Verify path | `--show-plan`, for logging |
| 8 | Plan Exists? | IF | No | Checks stdout for `plan_exists` |
| 9 | Regenerate Plan | Execute Command | Verify path | Recovery if plan missing |
| 10 | Run Batch | Execute Command | Verify path + dry-run first | `--batch`, the main engagement node |
| 11 | Parse Results | Code (JS) | No | Parses stdout into metrics |
| 12 | Daily Report | Execute Command | Verify path | Prints + logs to Sheets |
| 13 | Is Sunday? | IF | No | Weekday == 7 |
| 14 | Weekly Summary | Execute Command | Verify path | Sunday-only summary |
| 15 | Has Errors? | IF | No | Checks `has_errors` boolean |
| 16 | Format Error Payload | Code (JS) | No | Formats Slack message |
| 17 | Send Slack Alert | HTTP Request | **Yes - webhook URL** | Replace placeholder URL |
| 18 | No Errors - Done | No Operation | No | Visual endpoint |
| 19 | Weekday End | No Operation | No | Visual endpoint |

**Summary:** 8 nodes need path verification, 1 node needs Slack webhook configuration, 10 nodes work out of the box.

---

## 10. Troubleshooting

### Execute Command nodes have empty "Command" fields after import

**Cause:** You imported the workflow BEFORE enabling Execute Command nodes. When Execute Command is disabled, n8n strips the command content during import.

**Fix (Recommended): Delete and re-import**
1. Stop n8n if running: `pkill -f n8n`
2. Enable Execute Command:
   ```bash
   # Create persistent config
   mkdir -p ~/.n8n
   echo 'NODES_EXCLUDE=[]' > ~/.n8n/.env
   ```
3. Start n8n: `n8n start` or use `./start_n8n.sh`
4. In n8n UI, **delete** the imported workflow (three dots → Delete)
5. **Re-import** `n8n/LinkedIn Outreach.json`
6. Commands should now be populated in all Execute Command nodes

**Fix (Manual): Copy-paste commands**

If re-importing doesn't work, see [n8n/COMMANDS_REFERENCE.md](../n8n/COMMANDS_REFERENCE.md) for all 7 commands to copy-paste manually into each node.

---

### "Unrecognized node type: n8n-nodes-base.executeCommand"

**Cause:** n8n v2+ disables Execute Command by default for security.
**Fix:**
1. Create `~/.n8n/.env` file with: `NODES_EXCLUDE=[]`
2. OR use the startup script: `./start_n8n.sh`
3. Restart n8n completely after setting

### Execute Command nodes show "command not found: python" 

**Cause:** n8n can't find Python or you are pointing to the wrong path.
**Fix:** Every command in the workflow now uses the full path `/opt/anaconda3/bin/python3`. If your python is elsewhere, update the path in all nodes.

### Workflow runs but Health Check fails immediately

**Cause:** Health score is below 50 (circuit breaker open).
**Fix:**
1. Run manually: `python -c "from src.monitoring import HealthMonitor; m = HealthMonitor(); print(m.score)"`
2. If score is low, wait for the pause duration to expire
3. If this is a fresh install with no history, the score should be 100

### Is Monday? always goes to the wrong branch

**Cause:** Timezone mismatch. The expression uses `America/New_York` but your n8n instance might be in UTC.
**Fix:** Set workflow timezone (Section 6). Or set instance timezone: start n8n with `GENERIC_TIMEZONE=America/New_York`.

### Run Batch times out

**Cause:** The batch takes 15-45 minutes. n8n's default execution timeout might be shorter.
**Fix:** Set `EXECUTIONS_TIMEOUT=3600` (1 hour) when starting n8n:
```bash
EXECUTIONS_TIMEOUT=3600 N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand n8n start
```

### Parse Results shows 0 for everything

**Cause:** The batch output format doesn't match expected JSON lines.
**Fix:** Click the Run Batch node, check its stdout. Each engagement should output a JSON line with a `"status"` field. If the output format is different, adjust the parsing logic in the Parse Results Code node.

### Slack alerts not sending

**Cause:** Webhook URL is still the placeholder.
**Fix:** Double-click Send Slack Alert node, replace the URL. Test by temporarily setting Has Errors? to always-true (change condition to `1 equals 1`).

### Workflow doesn't fire at 9am

**Cause:** Workflow is not set to Active, or n8n isn't running.
**Fix:**
1. Check the Active toggle is green (top-right)
2. Check n8n process is running: `ps aux | grep n8n`
3. Check timezone settings (Section 6)
4. n8n must be running continuously -- if you close the terminal, the schedule stops

### Docker: "No such file or directory" for project path

**Cause:** The project directory isn't mounted into the container.
**Fix:** Add a volume mount in your docker run command:
```bash
-v "/Users/krantiy/Documents/Linkedin Automation Project":"/Users/krantiy/Documents/Linkedin Automation Project"
```
The path inside the container must match the path in the Execute Command nodes.

---

## Quick Start Checklist

```
[ ] n8n installed (npm or Docker)
[ ] N8N_NODES_INCLUDE=n8n-nodes-base.executeCommand set
[ ] n8n started and accessible at localhost:5678
[ ] Workflow JSON imported (19 nodes visible)
[ ] Project directory path verified in all Execute Command nodes
[ ] Slack webhook URL configured (or node deleted)
[ ] Workflow timezone set to America/New_York
[ ] Dry run successful via Manual Trigger
[ ] Test batch (3 profiles) successful
[ ] Full batch test successful
[ ] Workflow set to Active
[ ] n8n running as background process (pm2 or Docker)
```