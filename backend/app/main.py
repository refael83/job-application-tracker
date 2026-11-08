import csv
import io
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Optional

from datetime import date

from fastapi import Body, FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai_classify, email_scan
from .db import connect, init_db

STATUSES = ["הוגשה", "שיחת טלפון", "ראיון ראשון", "מטלת בית", "ראיון טכני",
            "ראיון סופי", "הצעה", "התקבלתי", "נדחיתי", "ללא מענה", "ביטלתי"]
FIELDS = ["company", "position", "url", "source", "location", "applied_date", "status",
          "resume_version", "contact", "salary", "follow_up_date", "notes"]
CSV_HEADERS = {
    "company": "חברה", "position": "תפקיד", "url": "קישור", "source": "מקור", "location": "מיקום",
    "applied_date": "תאריך הגשה", "status": "סטטוס", "resume_version": "גרסת קו\"ח",
    "contact": "איש קשר", "salary": "שכר", "follow_up_date": "תאריך מעקב", "notes": "הערות",
}


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(title="Job Application Tracker", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


class ApplicationIn(BaseModel):
    company: str
    position: str = ""
    url: str = ""
    source: str = ""
    location: str = ""
    applied_date: Optional[str] = None
    status: str = "הוגשה"
    resume_version: str = ""
    contact: str = ""
    salary: str = ""
    follow_up_date: Optional[str] = None
    notes: str = ""


class EventIn(BaseModel):
    status: str = ""
    note: str = ""


def fix_url(url):
    """A link without http(s):// (e.g. www.site.co.il/job/1) gets https:// so it is clickable."""
    url = (url or "").strip()
    if not url:
        return url
    if not re.match(r"https?://", url, re.I):
        url = f"https://{url}"
    # Chrome hides "www." in the address bar. These job boards redirect the bare domain to www. and drop the
    # query string (the job id), so the link would open an error page.
    return re.sub(r"^(https?://)(alljobs\.co\.il|drushim\.co\.il|jobmaster\.co\.il)(?=[/?#]|$)",
                  lambda m: m.group(1) + "www." + m.group(2), url, flags=re.I)


def norm(a: ApplicationIn):
    d = a.model_dump()
    d["company"] = d["company"].strip()
    if not d["company"]:
        raise HTTPException(400, "שם חברה חובה")
    d["applied_date"] = d["applied_date"] or None
    d["follow_up_date"] = d["follow_up_date"] or None
    d["status"] = d["status"] or "הוגשה"
    d["url"] = fix_url(d["url"])
    return d


def insert_app(conn, d, note="נוצרה"):
    row = conn.execute(
        f"INSERT INTO applications ({','.join(FIELDS)}) VALUES ({','.join(['%s'] * len(FIELDS))}) RETURNING id",
        [d[f] for f in FIELDS]).fetchone()
    conn.execute("INSERT INTO events (application_id, status, note) VALUES (%s,%s,%s)",
                 (row["id"], d["status"], note))
    return row["id"]


@app.get("/api/meta")
def meta():
    return {"statuses": STATUSES, "email_configured": email_scan.configured(),
            "ai_configured": ai_classify.configured(), "ai_provider": ai_classify.provider(),
            "mail_account": email_scan.mail_account(),
            "category_labels": email_scan.CATEGORY_LABELS}


@app.get("/api/applications")
def list_applications():
    with connect() as conn:
        return conn.execute("""
            SELECT a.*, COALESCE((SELECT MAX(ts) FROM events e WHERE e.application_id=a.id), a.created_at) AS last_activity,
                   (SELECT COUNT(*) FROM email_suggestions s WHERE s.application_id=a.id AND s.state='pending') AS pending_emails
            FROM applications a ORDER BY COALESCE(applied_date, created_at::date) DESC, id DESC""").fetchall()


@app.post("/api/applications", status_code=201)
def create_application(a: ApplicationIn):
    with connect() as conn:
        return {"id": insert_app(conn, norm(a))}


@app.put("/api/applications/{app_id}")
def update_application(app_id: int, a: ApplicationIn):
    d = norm(a)
    with connect() as conn:
        old = conn.execute("SELECT status FROM applications WHERE id=%s", (app_id,)).fetchone()
        if not old:
            raise HTTPException(404, "לא נמצא")
        conn.execute(f"UPDATE applications SET {','.join(f + '=%s' for f in FIELDS)}, updated_at=now() WHERE id=%s",
                     [d[f] for f in FIELDS] + [app_id])
        if d["status"] != old["status"]:
            conn.execute("INSERT INTO events (application_id, status, note) VALUES (%s,%s,'סטטוס עודכן')",
                         (app_id, d["status"]))
    return {"ok": True}


@app.delete("/api/applications/{app_id}")
def delete_application(app_id: int):
    with connect() as conn:
        conn.execute("DELETE FROM applications WHERE id=%s", (app_id,))
    return {"ok": True}


@app.get("/api/applications/{app_id}/events")
def list_events(app_id: int):
    with connect() as conn:
        return conn.execute("SELECT * FROM events WHERE application_id=%s ORDER BY ts DESC, id DESC",
                            (app_id,)).fetchall()


@app.get("/api/applications/{app_id}/emails")
def application_emails(app_id: int):
    """All emails linked to an application (found by scans or by the company search), newest first."""
    with connect() as conn:
        return conn.execute("""
            SELECT id, message_id, sender, subject, received_at, category, summary, state, match_confidence
            FROM email_suggestions WHERE application_id=%s AND state IN ('pending','applied','linked')
            ORDER BY received_at DESC NULLS LAST, id DESC""", (app_id,)).fetchall()


@app.post("/api/applications/{app_id}/find-emails")
def find_application_emails(app_id: int, days: int = 365):
    """Search emails for a specific job: collect the company's emails, and Claude decides which relate to this job."""
    if not email_scan.configured():
        raise HTTPException(400, "לא הוגדרו IMAP_USER / IMAP_PASSWORD בקובץ backend/.env")
    if not ai_classify.configured():
        raise HTTPException(400, "החיפוש לפי משרה עובד דרך Claude, ולא נמצא Claude Code מותקן או ANTHROPIC_API_KEY")
    with connect() as conn:
        apps = conn.execute("SELECT id, company, position, url, applied_date FROM applications").fetchall()
        known = [r["message_id"] for r in conn.execute(
            "SELECT message_id FROM email_suggestions WHERE application_id=%s OR state='dismissed'", (app_id,)).fetchall()]
    current = next((x for x in apps if x["id"] == app_id), None)
    if not current:
        raise HTTPException(404, "לא נמצא")
    key = email_scan._company_key(current["company"])
    siblings = [x for x in apps if x["id"] != app_id and email_scan._company_key(x["company"]) == key]
    try:
        found = email_scan.find_company_candidates(current["company"], max(1, min(days, 730)), known_ids=known)
    except Exception as exc:
        logging.getLogger("uvicorn.error").exception("company mail search failed")
        raise HTTPException(502, f"החיפוש נכשל: {_explain_imap_error(exc)}")

    stats = {}
    verdicts = ai_classify.match_emails(
        [(f["sender"], f["subject"], f["body"]) for f in found], current, siblings, stats) if found else []
    relevant = added = mine = 0
    with connect() as conn:
        for f, v in zip(found, verdicts):
            if v is None or not v["relevant"]:
                continue
            relevant += 1
            chosen = current if v["application"] == 0 else siblings[v["application"] - 1]
            mine += chosen["id"] == app_id
            cur = conn.execute("""INSERT INTO email_suggestions
                (message_id, application_id, sender, subject, received_at, snippet, category, suggested_status,
                 summary, state, match_confidence, job_url)
                VALUES (%s,%s,%s,%s,%s,'',%s,NULL,%s,'linked',%s,%s)
                ON CONFLICT (message_id) DO UPDATE SET application_id=EXCLUDED.application_id, state='linked',
                    match_confidence=EXCLUDED.match_confidence, category=EXCLUDED.category, summary=EXCLUDED.summary
                WHERE email_suggestions.application_id IS NULL OR email_suggestions.state='dismissed'
                   OR (email_suggestions.state='linked' AND email_suggestions.match_confidence <> 'manual')""",
                (f["message_id"], chosen["id"], f["sender"], f["subject"], f["received_at"], v["category"],
                 v["summary"], "low" if v["uncertain"] else "high", f.get("job_url", "")))
            added += cur.rowcount
            if f.get("job_url") and not (chosen.get("url") or ""):  # fill in the job link if there is none yet
                conn.execute("UPDATE applications SET url=%s WHERE id=%s AND url=''", (f["job_url"], chosen["id"]))
                chosen["url"] = f["job_url"]
    return {"found": len(found), "relevant": relevant, "added": added, "mine": mine,
            "errors": stats.get("ai_errors", 0)}


@app.post("/api/applications/{app_id}/events", status_code=201)
def add_event(app_id: int, e: EventIn):
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM applications WHERE id=%s", (app_id,)).fetchone():
            raise HTTPException(404, "לא נמצא")
        conn.execute("INSERT INTO events (application_id, status, note) VALUES (%s,%s,%s)",
                     (app_id, e.status.strip(), e.note.strip()))
        if e.status.strip():
            conn.execute("UPDATE applications SET status=%s, updated_at=now() WHERE id=%s", (e.status.strip(), app_id))
    return {"ok": True}


@app.post("/api/extract-screenshot")
async def extract_screenshot(request: Request):
    """Receive a raw image (PNG/JPEG/WEBP), extract applications from it and return them for editing. Nothing is stored."""
    image = await request.body()
    if not image or len(image) > ai_classify.MAX_IMAGE_BYTES:
        raise HTTPException(400, "התמונה ריקה או גדולה מדי (עד 8MB)")
    kind = ai_classify.detect_image(image)
    if not kind:
        raise HTTPException(400, "פורמט לא נתמך. יש להעלות PNG, JPG או WEBP")
    if not ai_classify.configured():
        raise HTTPException(400, "חילוץ מתמונה דורש Claude Code מותקן או ANTHROPIC_API_KEY ב-backend/.env")
    try:
        jobs = await run_in_threadpool(ai_classify.extract_screenshot, image, kind[0], kind[1],
                                       date.today().isoformat(), STATUSES)
    except Exception as exc:
        logging.getLogger("uvicorn.error").exception("screenshot extraction failed")
        raise HTTPException(502, f"החילוץ נכשל: {exc}")
    return {"jobs": jobs}


@app.get("/api/export.csv")
def export_csv():
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow([CSV_HEADERS[f] for f in FIELDS])
    for a in list_applications():
        w.writerow([a[f] if a[f] is not None else "" for f in FIELDS])
    return Response(("﻿" + out.getvalue()).encode("utf-8"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="applications.csv"'})


@app.post("/api/import")
def import_csv(text: str = Body(..., media_type="text/plain")):
    reverse = {v: k for k, v in CSV_HEADERS.items()}
    n = 0
    with connect() as conn:
        for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
            data = {reverse.get(k, k): (v or "").strip() for k, v in r.items() if k}
            if not data.get("company"):
                continue
            insert_app(conn, norm(ApplicationIn(**{k: v for k, v in data.items() if k in FIELDS})), "יובאה מ-CSV")
            n += 1
    return {"imported": n}


# ---------- email scanning ----------

def _explain_imap_error(exc):
    text = str(exc)
    low = text.lower()
    if "authenticationfailed" in low or "invalid credentials" in low or "application-specific" in low:
        return (f"ההתחברות נדחתה ({text}). ב-Gmail צריך סיסמת אפליקציה (לא הסיסמה הרגילה) "
                "וגם IMAP_USER עם הכתובת המלאה. ודא שאין רווחים או גרשיים ב-.env")
    if "imap" in low and ("disabled" in low or "not enabled" in low):
        return f"IMAP כבוי בחשבון ({text}). ב-Gmail: הגדרות > העברה ו-POP/IMAP > הפעל IMAP"
    if isinstance(exc, (OSError,)):
        return f"בעיית רשת או IMAP_HOST שגוי ({text})"
    return f"{type(exc).__name__}: {text}"


@app.post("/api/email/scan")
def scan_email(days: int = 30, use_ai: bool = False):
    """Scan the mailbox for the last `days` days.

    An email that matches a tracked job is linked to that job right away. If it also suggests a new status, it is
    kept as pending so the status change still needs the user's approval. Emails about jobs that are not tracked
    yet are kept as pending "discovered jobs". Every run is recorded so the UI can show when it last ran."""
    if not email_scan.configured():
        raise HTTPException(400, "לא הוגדרו IMAP_USER / IMAP_PASSWORD בקובץ backend/.env")
    if use_ai and not ai_classify.configured():
        raise HTTPException(400, "לא הוגדר ANTHROPIC_API_KEY בקובץ backend/.env, ו-Claude Code לא נמצא")
    stats = {}
    days = max(1, min(days, 365))
    with connect() as conn:
        apps = conn.execute("SELECT id, company, position, url, status, applied_date FROM applications").fetchall()
        known = [r["message_id"] for r in conn.execute("SELECT message_id FROM email_suggestions").fetchall()]
    try:
        found = email_scan.scan(apps, days, known, use_ai, stats)
    except Exception as exc:  # login / network errors are shown to the user
        logging.getLogger("uvicorn.error").exception("email scan failed")
        raise HTTPException(502, f"הסריקה נכשלה: {_explain_imap_error(exc)}")

    by_id = {a["id"]: a for a in apps}
    per_job = {}
    linked = needs_review = discovered = 0
    with connect() as conn:
        for f in found:
            app_id = f["application_id"]
            if app_id is None:
                state = "pending"
                discovered += 1
            else:
                suggested = f["suggested_status"]
                state = "pending" if suggested and suggested != by_id[app_id]["status"] else "linked"
                linked += state == "linked"
                needs_review += state == "pending"
                per_job[app_id] = per_job.get(app_id, 0) + 1
            conn.execute("""INSERT INTO email_suggestions
                (message_id, application_id, sender, subject, received_at, snippet, category, suggested_status,
                 guessed_company, guessed_position, summary, match_confidence, job_url, state)
                VALUES (%(message_id)s,%(application_id)s,%(sender)s,%(subject)s,%(received_at)s,%(snippet)s,
                        %(category)s,%(suggested_status)s,%(guessed_company)s,%(guessed_position)s,%(summary)s,
                        %(match_confidence)s,%(job_url)s,%(state)s)
                ON CONFLICT (message_id) DO NOTHING""", {**f, "state": state})
        ran_at = conn.execute(
            "INSERT INTO scan_runs (days, scanned_new, linked, needs_review, discovered) VALUES (%s,%s,%s,%s,%s) "
            "RETURNING ran_at", (days, len(found), linked, needs_review, discovered)).fetchone()["ran_at"]
    updated = sorted(
        ({"id": i, "company": by_id[i]["company"], "position": by_id[i]["position"], "count": n}
         for i, n in per_job.items()), key=lambda u: -u["count"])
    return {"new": len(found), "linked": linked, "needs_review": needs_review, "discovered": discovered,
            "updated": updated, "ran_at": ran_at, "days": days, **stats}


@app.get("/api/email/last-scan")
def last_scan():
    """The most recent scan run (or null if there was none)."""
    with connect() as conn:
        return conn.execute("SELECT * FROM scan_runs ORDER BY ran_at DESC, id DESC LIMIT 1").fetchone()


@app.get("/api/email/suggestions")
def list_suggestions(state: str = "pending"):
    """Also includes emails about jobs that were discovered but are not tracked yet (empty application_id)."""
    with connect() as conn:
        return conn.execute("""
            SELECT s.*, a.company, a.position, a.status AS current_status
            FROM email_suggestions s LEFT JOIN applications a ON a.id = s.application_id
            WHERE s.state=%s ORDER BY s.received_at DESC NULLS LAST, s.id DESC""", (state,)).fetchall()


class DiscoveredIn(BaseModel):
    company: str
    position: str = ""
    url: str = ""
    status: str = "הוגשה"


@app.post("/api/email/suggestions/{sid}/create-application")
def create_from_suggestion(sid: int, d: DiscoveredIn):
    """Create a new application from a discovered email, and attach other pending emails from the same company."""
    company = d.company.strip()
    if not company:
        raise HTTPException(400, "שם חברה חובה")
    with connect() as conn:
        s = conn.execute("SELECT * FROM email_suggestions WHERE id=%s AND state='pending' AND application_id IS NULL",
                         (sid,)).fetchone()
        if not s:
            raise HTTPException(404, "לא נמצא")
        applied = s["received_at"].date() if s["received_at"] else None
        app_id = conn.execute(
            "INSERT INTO applications (company, position, url, source, applied_date, status) VALUES (%s,%s,%s,'מייל',%s,%s) RETURNING id",
            (company, d.position.strip(), fix_url(d.url or s["job_url"]), applied, d.status or "הוגשה")).fetchone()["id"]
        conn.execute("INSERT INTO events (application_id, ts, status, note) VALUES (%s, COALESCE(%s, now()), %s, %s)",
                     (app_id, s["received_at"], d.status or "הוגשה", f"זוהתה ממייל: {s['subject']}"))
        conn.execute("UPDATE email_suggestions SET state='applied', application_id=%s WHERE id=%s", (app_id, sid))
        conn.execute("""UPDATE email_suggestions SET application_id=%s
                        WHERE state='pending' AND application_id IS NULL AND lower(guessed_company)=lower(%s)""",
                     (app_id, s["guessed_company"] or company))
    return {"id": app_id}


@app.post("/api/email/suggestions/{sid}/apply")
def apply_suggestion(sid: int, status: Optional[str] = None):
    """Approve an email: add an event to the history and update the status (the suggested one, or one chosen manually)."""
    with connect() as conn:
        s = conn.execute("SELECT * FROM email_suggestions WHERE id=%s AND state='pending'", (sid,)).fetchone()
        if not s:
            raise HTTPException(404, "לא נמצא")
        new_status = (status or s["suggested_status"] or "").strip()
        conn.execute("INSERT INTO events (application_id, ts, status, note) VALUES (%s, COALESCE(%s, now()), %s, %s)",
                     (s["application_id"], s["received_at"], new_status, f"מייל: {s['subject']}"))
        if new_status:
            conn.execute("UPDATE applications SET status=%s, updated_at=now() WHERE id=%s",
                         (new_status, s["application_id"]))
        if s["job_url"]:  # fill in the job link if there is none yet
            conn.execute("UPDATE applications SET url=%s WHERE id=%s AND url=''", (s["job_url"], s["application_id"]))
        conn.execute("UPDATE email_suggestions SET state='applied' WHERE id=%s", (sid,))
    return {"ok": True}


class ReassignIn(BaseModel):
    application_id: int


@app.post("/api/email/suggestions/{sid}/reassign")
def reassign_suggestion(sid: int, d: ReassignIn):
    """Move an email to another application (e.g. when several jobs exist at one company). A manual move is not overwritten by later searches."""
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM applications WHERE id=%s", (d.application_id,)).fetchone():
            raise HTTPException(404, "ההגשה לא נמצאה")
        cur = conn.execute("UPDATE email_suggestions SET application_id=%s, match_confidence='manual' WHERE id=%s",
                           (d.application_id, sid))
        if not cur.rowcount:
            raise HTTPException(404, "המייל לא נמצא")
    return {"ok": True}


@app.post("/api/email/suggestions/{sid}/dismiss")
def dismiss_suggestion(sid: int):
    with connect() as conn:
        conn.execute("UPDATE email_suggestions SET state='dismissed' WHERE id=%s", (sid,))
    return {"ok": True}


# Serve the built UI (frontend/dist) from the same server, so a single process is enough. Must come last, after the API routes.
DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")
if os.path.isdir(DIST):
    app.mount("/", StaticFiles(directory=DIST, html=True), name="ui")
