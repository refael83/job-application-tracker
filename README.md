# Job Application Tracker

A local app for tracking the jobs you applied to. The UI is in Hebrew (RTL); code, comments and docs are in English.

- **Client:** React + Vite (`frontend/`)
- **Server:** Python + FastAPI (`backend/`)
- **Database:** PostgreSQL
- **Email:** read-only IMAP scanning that finds replies to your applications and suggests status updates
- **AI (optional):** Claude classifies emails, matches them to the right job, and reads screenshots

## First run

1. Make sure PostgreSQL is running (on this machine it is the `postgresql-x64-18` service).
2. Create the settings file and put the password of the `postgres` user in it:
   ```
   copy backend\.env.example backend\.env
   ```
   Edit `backend\.env` and fill in `PGPASSWORD`. The server creates the `job_tracker` database and its tables by itself.
3. Start the app with the **Job Tracker** shortcut on the Desktop (or `start.bat`). A single PowerShell window runs the
   server and shows the live log, and the browser opens at http://localhost:8000. Stop it with Ctrl+C or by closing the window.
   - **Background mode, no window at all:** `start.vbs`. Stop it with `stop.vbs`. The log goes to `logs\server.log`.
   - **After changing frontend code:** run `build.bat` (rebuilds `frontend\dist`).
   - **Dev mode with automatic restart:** `start-dev.bat` (or `start.ps1 -Dev`). The server reloads whenever a `.py` or `.env`
     file in `backend` changes, and the UI is rebuilt whenever a file in `frontend\src` changes (refresh the browser yourself).
     Manual equivalent: `backend\.venv\Scripts\python backend\run.py --reload`.

Reinstalling (if `.venv` or `node_modules` are missing):
```
cd backend && python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
cd ..\frontend && npm install
```

## Features

- Applications table with search, status filter, statistics (in progress, interviews, offers, response rate) and a
  follow-up reminder for applications that went quiet.
- Per-application details: status history timeline, notes, contact, salary, resume version, **job link** (a 🔗 button in the table).
- CSV export and import (opens in Excel), handy for importing applications you already track in a spreadsheet.
- Links without `http(s)://` are completed to `https://` automatically.

## Email scanning

In the "תשובות במייל" (email replies) tab, click the scan button. To make it work with Gmail:

1. Turn on 2-step verification for your Google account.
2. Create an **app password** at https://myaccount.google.com/apppasswords
3. In `backend\.env` set `IMAP_USER` (your email address) and `IMAP_PASSWORD` (the app password, not your regular password;
   spaces in it are ignored).
4. Restart the server.

How it works:
- The scan is **read-only**: it never deletes, modifies or marks messages as read.
- On Gmail the search runs on Google's side (`X-GM-RAW`, the same syntax as the Gmail search box), so only matching emails
  are downloaded. Promotions, social and forum tabs and job-alert/newsletter subjects are excluded.
- **Discovering new applications:** an email about a job (confirmation, interview invite, rejection...) from a company
  that is not tracked yet appears under "jobs discovered". The company, position and job link are guessed (you can fix them),
  and "add to tracking" creates the application with the email's date and status. Other emails from that company attach to it.
- Reply types are detected by Hebrew and English keywords (rejection, interview, assignment, offer, confirmation) and a
  status is **suggested**. No status changes until you approve it; you can also pick another status or dismiss the email.
- Each email card shows a short summary (when the AI is on) and a link that opens the original email in Gmail.
- Already scanned emails do not show up again.
- When a company has several applications, an email is matched to the one whose position title and dates fit best.
  Uncertain matches are flagged, and you can move an email to a sibling application (a manual move is never overwritten).

### Finding all emails of one job

Open an application and click "find emails of this job (via Claude)". Candidate emails of the company are collected from
Gmail, Claude decides which ones are personal messages about *this* job (and not newsletters, job alerts or other roles),
and only those are linked, with a category and a one-line summary. This search requires Claude (see below).

## AI classification (optional)

In the email tab, "use AI for accurate classification" is ticked by default when Claude is available. Claude reads each
email that passed filtering and returns whether it concerns your application, the company, the position, the reply type
and a short summary. It understands wordings that keyword rules miss.

**Option A, no API key (uses your subscription):** if Claude Code is installed and logged in (the `claude` command works),
the server runs it in the background without tools and sends emails in batches of 8. No setup is needed. Usage counts
toward your plan's limits, and a large scan can use a noticeable part of them.

**Option B, API key:** create a key at https://console.anthropic.com/ (billed separately per use, not included in a
subscription) and add `ANTHROPIC_API_KEY=...` to `backend\.env`. When a key exists it is preferred over Claude Code;
force a provider with `AI_PROVIDER=cli` or `AI_PROVIDER=api`.

Restart the server after changing `.env`.

Privacy: only emails that passed filtering are sent, and only the sender, the subject and the first 2,000 characters of
the body. When the option is off, nothing is sent to any external service. If an AI call fails for an email, the scan falls
back to the keyword rules for it.

## Adding from a screenshot

In the applications tab, click "📷 מצילום מסך" (from a screenshot). A dialog opens where you can paste a screenshot
(Ctrl+V), drop a file, or choose an image, and optionally enter the job link. Pasting anywhere on the page also opens the
dialog with the image loaded. **Nothing is sent until you click "אישור" (Confirm).** Claude then reads the image and extracts
company, position, application date, source, status and notes, from either a list of your applications on a job site or a
single job posting page. You get an editable table and only what you approve is added. The image is sent to Anthropic,
is not stored on disk or in the database, and must be PNG, JPG or WEBP up to 8 MB. If the address bar is visible in the
screenshot, Claude can fill in the link too.

## Structure

```
backend/run.py              launcher: server + built UI, optional --reload / --no-browser
backend/app/main.py         API (applications, history, CSV, emails, screenshot extraction)
backend/app/db.py           Postgres connection + schema creation
backend/app/email_scan.py   IMAP scanning, Gmail search, company/position matching, rules
backend/app/ai_classify.py  Claude integration (Claude Code CLI or API): classification, matching, vision
frontend/src/               React UI
start.bat / start.ps1       run in a PowerShell window (start-dev.bat = auto-restart mode)
start.vbs / stop.vbs        run / stop in the background without a window
build.bat                   rebuild the UI
```
