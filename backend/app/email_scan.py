"""Mailbox scanning (IMAP): finds replies about jobs the user applied to.

The scan is read-only (BODY.PEEK): it never modifies, marks as read or deletes mail.
It does not change statuses by itself: it creates "suggestions" that the user approves or dismisses in the UI.
"""
import email
import imaplib
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from html import unescape

from . import ai_classify

# Order matters: rejection comes first, because a rejection email sometimes also says "thanks for applying".
RULES = [
    ("rejection", "נדחיתי", [
        "לצערנו", "לא נמשיך", "בחרנו להתקדם עם", "החלטנו להתקדם עם", "אינך מתאים", "לא נוכל להמשיך",
        "משרה אוישה", "unfortunately", "not moving forward", "not be moving forward",
        "other candidates", "decided to pursue", "will not be proceeding", "regret to inform",
        "position has been filled"]),
    ("offer", "הצעה", [
        "שמחים להציע", "הצעת העסקה", "מכתב הצעה", "offer letter", "pleased to offer",
        "excited to offer", "job offer"]),
    ("assessment", "מטלת בית", [
        "מטלת בית", "מטלה", "תרגיל בית", "בוחן", "home assignment", "take-home", "coding challenge",
        "assessment", "hackerrank", "codility", "codesignal", "leetcode"]),
    ("technical_interview", "ראיון טכני", [
        "ראיון טכני", "technical interview", "technical round", "coding interview", "system design"]),
    ("phone_screen", "שיחת טלפון", [
        "שיחת היכרות", "שיחת טלפון", "שיחה קצרה", "phone screen", "intro call", "introductory call",
        "quick call", "recruiter call"]),
    ("interview", "ראיון ראשון", [
        "זימון לראיון", "ראיון", "נשמח לתאם", "נשמח לפגוש", "לקבוע פגישה", "schedule an interview",
        "invite you to interview", "interview", "availability", "calendly"]),
    ("received", None, [
        "קיבלנו את קורות", "קיבלנו את מועמדותך", "תודה על פנייתך", "תודה שהגשת", "תודה על הגשת",
        "thank you for applying", "application received", "received your application",
        "we have received"]),
]

CATEGORY_LABELS = {
    "rejection": "דחייה", "offer": "הצעה", "assessment": "מטלה", "technical_interview": "ראיון טכני",
    "phone_screen": "שיחת טלפון", "interview": "זימון לראיון", "received": "אישור קבלה", "other": "אחר",
}


def mail_account():
    """The account address, used to build "open in Gmail" links. Empty if the host is not Gmail."""
    if "gmail" not in os.getenv("IMAP_HOST", "imap.gmail.com").lower():
        return ""
    return (os.getenv("IMAP_USER") or "").strip()


def configured():
    return bool(os.getenv("IMAP_USER") and os.getenv("IMAP_PASSWORD"))


def _decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # unknown charset in the header: decode chunk by chunk
        out = []
        for chunk, charset in decode_header(value):
            out.append(_safe_decode(chunk, charset) if isinstance(chunk, bytes) else chunk)
        return "".join(out)


def _safe_decode(payload, charset):
    """Decode bytes to text even when Python does not know the charset (e.g. iso-8859-8-i)."""
    charset = (charset or "utf-8").lower()
    if charset.startswith("iso-8859-8"):
        charset = "iso-8859-8"
    elif charset in ("windows-1255", "cp1255"):
        charset = "cp1255"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _body_text(msg):
    plain, html = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html") or part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = _safe_decode(payload, part.get_content_charset())
        if ctype == "text/plain":
            plain += text
        else:
            html += text
    if not plain and html:
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        plain = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", plain).strip()


_URL = re.compile(r"https?://[^\s<>\"')\]]+")
JOB_HOSTS = ("alljobs.co.il", "drushim.co.il", "jobmaster.co.il", "linkedin.com/jobs", "greenhouse.io", "lever.co",
             "comeet.com", "comeet.co", "workable.com", "smartrecruiters.com", "ashbyhq.com", "myworkdayjobs.com",
             "indeed.com/viewjob", "jobs.", "careers.", "/careers")
PATH_HINTS = ("/job/", "/jobs/", "/position", "/career", "/apply", "viewjob", "jobid", "job_id", "משרה")
BAD_LINK = ("unsubscribe", "optout", "opt-out", "privacy", "terms", "mailto:", "pixel", ".png", ".jpg", ".gif",
            "preferences", "facebook.com", "twitter.com", "instagram.com", "help.", "/open?")


def _links(msg):
    """All links in a message (plain text and HTML href), in order of appearance, without duplicates."""
    found = []
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html") or part.get_filename():
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        text = _safe_decode(payload, part.get_content_charset())
        if ctype == "text/html":
            found += re.findall(r"href=[\"'](https?://[^\"']+)", text, re.I)
        found += _URL.findall(text)
    return list(dict.fromkeys(found))


def pick_job_url(links):
    """The link that looks most like a job link (job board / ATS / a /job/ path). Empty if none is convincing."""
    best, best_score = "", 0
    for url in links:
        low = url.lower()
        if any(b in low for b in BAD_LINK):
            continue
        score = (2 if any(h in low for h in JOB_HOSTS) else 0) + (2 if any(h in low for h in PATH_HINTS) else 0)
        if score > best_score:
            best, best_score = url.rstrip(".,;"), score
    return best if best_score >= 2 else ""


def classify(subject, body):
    text = f"{subject} {body[:4000]}".lower()
    for category, status, keywords in RULES:
        if any(k.lower() in text for k in keywords):
            return category, status
    return "other", None


def match_application(applications, sender, subject, body):
    """Return the most likely application for an email, by company name in the sender, subject or body."""
    name, addr = parseaddr(sender)
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    haystack_head = f"{name} {domain} {subject}".lower()
    haystack_body = body[:3000].lower()
    best, best_score = None, 0
    for app in applications:
        company = (app["company"] or "").strip().lower()
        if len(company) < 2:
            continue
        compact = re.sub(r"[^\w]", "", company)
        score = 0
        if company in haystack_head or (len(compact) >= 3 and compact in domain.replace("-", "").replace(".", "")):
            score += 3
        if company in haystack_body:
            score += 1
        # if there are several applications at the same company, prefer the one whose position is mentioned
        position = (app["position"] or "").strip().lower()
        if score and position and position in f"{subject} {body[:3000]}".lower():
            score += 1
        if score > best_score:
            best, best_score = app, score
    return best if best_score >= 3 else None


_STOP = {"the", "for", "and", "a", "an", "to", "of", "position", "role", "job", "ב", "ל", "של", "ו", "את", "ת"}
_SYNONYMS = {
    "developer": "dev", "engineer": "dev", "programmer": "dev", "מפתח": "dev", "מפתחת": "dev", "מהנדס": "dev",
    "מהנדסת": "dev", "software": "sw", "תוכנה": "sw", "fullstack": "fullstack", "פולסטאק": "fullstack",
    "backend": "backend", "בקאנד": "backend", "frontend": "frontend", "פרונטאנד": "frontend",
    "junior": "junior", "ג": "junior", "senior": "senior", "סניור": "senior", "python": "python",
    "פייתון": "python", "java": "java", "ג'אווה": "java", "devops": "devops", "qa": "qa", "data": "data",
    "דאטה": "data", "מנהל": "lead", "lead": "lead", "מוביל": "lead",
}


def _tokens(text):
    text = (text or "").lower()
    text = re.sub(r"full[\s-]*stack", "fullstack", text)
    text = re.sub(r"back[\s-]*end", "backend", text)
    text = re.sub(r"front[\s-]*end", "frontend", text)
    words = re.findall(r"[\w']+", text)
    return {_SYNONYMS.get(w, w) for w in words if w not in _STOP and len(w) > 1}


def position_score(position, text):
    """0..1: the share of the meaningful words of the position title found in the text (with synonyms, Hebrew/English)."""
    wanted = _tokens(position)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(text)) / len(wanted)


def _company_key(name):
    return re.sub(r"[^\w]", "", (name or "").lower())


def refine_application(applications, app, text, received):
    """When several applications exist at the same company: pick the one matching the email's position and date.

    Returns (application, confidence) where confidence is "high" or "low" (the email does not tell them apart)."""
    if not app:
        return None, "high"
    key = _company_key(app["company"])
    siblings = [a for a in applications if _company_key(a["company"]) == key]
    if len(siblings) <= 1:
        return app, "high"
    scored = []
    for a in siblings:
        pos = position_score(a["position"], text)
        fit = 0.0
        applied = a.get("applied_date")
        if received and applied:
            days = (received.date() - applied).days
            fit = -2.0 if days < 0 else 0.5 / (1 + days / 30)  # an email before the application is implausible; closer to the date is better
        scored.append((pos * 3 + fit, pos, a))
    scored.sort(key=lambda t: t[0], reverse=True)
    best, runner_up = scored[0], scored[1]
    confident = best[1] >= 0.5 and best[0] - runner_up[0] >= 0.5
    return best[2], "high" if confident else "low"


JOB_CONTEXT = [
    "apply", "applying", "application", "applied", "candidate", "position", "resume", "recruit",
    "hiring", "interview", "קורות חיים", "מועמד", "משרה", "תפקיד", "גיוס", "ראיון", "הגשת"]

# Senders that are a platform / mail provider rather than the company itself: the company name must come from the subject or display name
PLATFORMS = ("alljobs", "drushim", "jobmaster", "linkedin", "greenhouse", "lever.co", "comeet", "workable",
             "smartrecruiters", "myworkday", "icims", "ashbyhq", "indeed", "glassdoor", "gmail.com",
             "outlook.com", "hotmail.com", "yahoo.com", "mailchimp", "sendgrid", "amazonses")
PLATFORM_NAMES = {"linkedin", "alljobs", "drushim", "jobmaster", "indeed", "glassdoor", "greenhouse",
                  "lever", "comeet", "workable", "smartrecruiters", "workday", "דרושים", "אולג'ובס"}
GENERIC_WORDS = re.compile(
    r"\b(recruiting|recruitment|recruiter|careers?|talent|acquisition|hr|jobs?|hiring|team|"
    r"no-?reply|notifications?|via|the)\b|גיוס|משאבי אנוש|קריירה|צוות|דרושים", re.I)

_SUBJ_POS_AT_COMPANY = re.compile(
    r"(?:application|applying|applied)\s+(?:to|for)\s+(?:the\s+)?(.+?)\s+(?:at|with|@)\s+(.+?)\s*(?:$|[-–|!.:,])", re.I)
_SUBJ_COMPANY = [
    re.compile(r"(?:thank(?:s| you) for applying (?:to|at|with)|your application (?:to|at|with)|application (?:to|at|with))"
               r"\s+(.+?)\s*(?:$|[-–|!.:,])", re.I),
    re.compile(r"(?:מועמדותך|הגשת מועמדות|קורות החיים שלך)\s+(?:ל|אל|ב)-?(.+?)\s*(?:$|[-–|!.:,])"),
]
_POSITION = [
    re.compile(r"(?:for the|for a|for an|as an?)\s+(.{3,70}?)\s+(?:position|role|opening)", re.I),
    re.compile(r"(?:position|role|job title)\s*:\s*(.{3,70}?)\s*(?:$|[|.,\n])", re.I),
    re.compile(r"(?:למשרת|משרת|לתפקיד|תפקיד:?)\s+([^-–|!.:,\n]{3,70})"),
]


def _clean_name(text):
    text = GENERIC_WORDS.sub(" ", text or "")
    text = re.sub(r"[\"'<>()\[\]|]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" -–.,:")


def extract_company_position(sender, subject, body):
    """Guess (company, position) from an email that matched no existing application. Returns (None, ..) if no company can be identified."""
    name, addr = parseaddr(sender)
    domain = addr.split("@")[-1].lower() if "@" in addr else ""
    company = position = None

    m = _SUBJ_POS_AT_COMPANY.search(subject)
    if m:
        position, company = m.group(1).strip(), m.group(2).strip()
    if not company:
        for pat in _SUBJ_COMPANY:
            m = pat.search(subject)
            if m:
                company = m.group(1).strip()
                break
    if not company:
        display = _clean_name(name)
        if display and display.lower() not in PLATFORM_NAMES:
            company = display
    if not company and domain and not any(p in domain for p in PLATFORMS):
        parts = domain.split(".")
        core = parts[-3] if len(parts) >= 3 and parts[-2] in ("co", "com", "org") else parts[-2] if len(parts) >= 2 else ""
        company = core.capitalize() if core else None

    if company:
        company = _clean_name(company)[:80] or None
    if not position:
        for pat in _POSITION:
            m = pat.search(f"{subject}\n{body[:2000]}")
            if m:
                position = m.group(1).strip()
                break
    return company, (position or "")[:80]


SENDER_HINTS = ("career", "jobs", "job-", "recruit", "talent", "hiring", "comeet", "greenhouse", "lever.co",
                "workable", "alljobs", "drushim", "jobmaster", "linkedin", "smartrecruiters", "ashbyhq",
                "icims", "myworkday", "גיוס", "קריירה", "משאבי אנוש")
SUBJECT_HINTS = [k.lower() for _, _, kws in RULES for k in kws] + JOB_CONTEXT + ["משרה", "קורות", "job"]
HEADER_FIELDS = "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])"
HEADER_CHUNK = 300
BODY_LIMIT = 40000  # bytes: enough for the email text, without attachments


def _header_candidate(applications, sender, subject):
    """Cheap header-only filter, so bodies are downloaded only for emails that may relate to jobs."""
    if match_application(applications, sender, subject, ""):
        return True
    low = f"{sender} {subject}".lower()
    return any(h in low for h in SENDER_HINTS) or any(h in subject.lower() for h in SUBJECT_HINTS)


GMAIL_SUBJECT_WORDS = [
    "your application", "application received", "applying", "thank you for applying", "interview", "assessment",
    "unfortunately", "job offer", "next steps", "moving forward", "מועמדות", "מועמדותך", "קורות חיים", "ראיון",
    "לצערנו", "מטלה", "תודה על פנייתך", "תודה שהגשת", "המשך תהליך"]
# Gmail-side exclusions: promotions / social / forums, and job alerts / newsletters by subject
GMAIL_EXCLUDE = ('-category:promotions -category:social -category:forums '
                 '-subject:("job alert" OR "jobs for you" OR "new jobs" OR newsletter OR webinar OR "משרות חדשות" '
                 'OR "משרות שמתאימות" OR "משרות מומלצות" OR "התראת משרות" OR מבצע OR הנחה)')
GMAIL_MAX = 300


def _gmail_search(imap, applications, days):
    """Search on Gmail's side (same query syntax as the search box). Returns only matching messages, downloading nothing."""
    quote = lambda t: f'"{t}"' if " " in t else t
    parts = ["subject:(" + " OR ".join(quote(w) for w in GMAIL_SUBJECT_WORDS) + ")"]
    companies = sorted({(a["company"] or "").replace('"', "").strip() for a in applications})
    companies = [c for c in companies if len(c) >= 2]
    if companies:
        parts.append("from:(" + " OR ".join(quote(c) for c in companies) + ")")
    query = f"newer_than:{days}d (" + " OR ".join(parts) + f") {GMAIL_EXCLUDE}"
    imap._encoding = "utf-8"  # imaplib's way of sending Hebrew in a query
    escaped = query.replace("\\", "\\\\").replace('"', '\\"')
    typ, data = imap.search(None, "X-GM-RAW", f'"{escaped}"')
    if typ != "OK":
        raise imaplib.IMAP4.error("X-GM-RAW search failed")
    return data[0].split()[-GMAIL_MAX:]


NEG_SUBJECT = ["job alert", "jobs for you", "new jobs", "jobs you may", "recommended jobs", "newsletter", "webinar",
               "% off", "free trial", "משרות חדשות", "משרות שמתאימות", "משרות מומלצות", "התראת משרות", "מבצע", "הנחה"]
NEG_BODY = ["unsubscribe", "manage your preferences", "view in browser", "view this email in your browser",
            "להסרה מרשימת", "הסרה מרשימת התפוצה", "לביטול הרשמה", "הצג בדפדפן", "לצפייה בדפדפן"]
PERSONAL = ["your application", "you applied", "you've applied", "thank you for applying", "your interview",
            "קורות החיים שלך", "הגשת מועמדות", "מועמדותך", "הראיון שלך"]


def is_promotional(subject, body):
    """Ads, newsletters and job alerts: skip them unless there is a clear sign the email is personal and about an application."""
    subj = subject.lower()
    text = f"{subject} {body[:1500]}".lower()
    if any(k in subj for k in NEG_SUBJECT):
        return True
    return any(k in body.lower() for k in NEG_BODY) and not any(k in text for k in PERSONAL)


def _fetched_bytes(parts):
    return [(p[0], p[1]) for p in parts if isinstance(p, tuple)]


CATEGORY_STATUS = {category: status for category, status, _ in RULES}


def match_by_company(applications, company, position=""):
    """Match a company name returned by the AI to an existing application (equality or containment, case-insensitive)."""
    norm = lambda s: re.sub(r"[^\w]", "", (s or "").lower())
    target = norm(company)
    if len(target) < 2:
        return None
    hits = [a for a in applications
            if norm(a["company"]) and (norm(a["company"]) == target
                                       or (min(len(norm(a["company"])), len(target)) >= 3
                                           and (norm(a["company"]) in target or target in norm(a["company"]))))]
    if len(hits) > 1 and position:
        pos = [a for a in hits if (a["position"] or "").strip().lower() == position.strip().lower()]
        hits = pos or hits
    return hits[0] if hits else None


def scan(applications, days=30, known_ids=(), use_ai=False, stats=None):
    """Return a list of new relevant emails. known_ids = message-ids that were already scanned.

    Stage 1: headers of all emails in range, in batched requests. Stage 2: a partial body only for candidates.
    """
    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    user = (os.getenv("IMAP_USER") or "").strip()
    # Google shows app passwords in groups separated by spaces; the spaces are not part of the password
    password = re.sub(r"\s+", "", os.getenv("IMAP_PASSWORD") or "")
    folder = os.getenv("IMAP_FOLDER", "INBOX")
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    own = user.lower()
    results, seen = [], set(known_ids)
    stats = stats if stats is not None else {}
    stats.setdefault("ai_used", 0)
    stats.setdefault("ai_errors", 0)

    imap = imaplib.IMAP4_SSL(host, timeout=60)
    try:
        imap.login(user, password)
        imap.select(f'"{folder}"', readonly=True)
        candidates = []  # (message number, mid, sender, subject); mid/sender/subject are None if headers were not loaded
        nums = None
        if "gmail" in host.lower():
            try:
                nums = _gmail_search(imap, applications, days)
                candidates = [(n, None, None, None) for n in nums]
            except Exception:  # fall back to the generic method
                nums = None
        if nums is None:
            _, data = imap.search(None, "SINCE", since)
            nums = data[0].split()
        for i in range(0, 0 if candidates else len(nums), HEADER_CHUNK):
            chunk = nums[i:i + HEADER_CHUNK]
            _, parts = imap.fetch(b",".join(chunk).decode(), HEADER_FIELDS)
            for meta, raw in _fetched_bytes(parts):
                try:
                    num = meta.split()[0]
                    hdr = email.message_from_bytes(raw)
                    sender, subject = _decode(hdr.get("From")), _decode(hdr.get("Subject"))
                    mid = (hdr.get("Message-ID") or "").strip() or f"{sender}|{hdr.get('Date')}|{subject}"
                except Exception:
                    continue
                if mid in seen or (own and own in sender.lower()):
                    continue
                if _header_candidate(applications, sender, subject):
                    candidates.append((num, mid, sender, subject))

        items = []  # (mid, sender, subject, body, msg) of downloaded emails
        for num, mid, sender, subject in reversed(candidates):
            try:
                _, parts = imap.fetch(num.decode(), f"(BODY.PEEK[]<0.{BODY_LIMIT}>)")
                fetched = _fetched_bytes(parts)
                if not fetched:
                    continue
                msg = email.message_from_bytes(fetched[0][1])
                body = _body_text(msg)
                if mid is None:  # came from a Gmail search: read the headers from the message itself
                    sender, subject = _decode(msg.get("From")), _decode(msg.get("Subject"))
                    mid = (msg.get("Message-ID") or "").strip() or f"{sender}|{msg.get('Date')}|{subject}"
                    if mid in seen or (own and own in sender.lower()):
                        continue
            except Exception:
                continue
            if is_promotional(subject, body):
                seen.add(mid)
                continue
            items.append((mid, sender, subject, body, msg))

        ai_results = []
        if use_ai:
            ai_results = ai_classify.analyze_many(
                [(snd, sub, bd) for _, snd, sub, bd, _ in items], [a["company"] for a in applications], stats)
        for idx, (mid, sender, subject, body, msg) in enumerate(items):
            ai = ai_results[idx] if use_ai else None
            guessed_company = guessed_position = None
            try:
                received = parsedate_to_datetime(msg.get("Date"))
                if received.tzinfo is None:
                    received = received.replace(tzinfo=timezone.utc)
            except Exception:
                received = None
            if ai is not None:
                if not ai["job_related"]:
                    continue
                category = ai["category"]
                status = CATEGORY_STATUS.get(category)
                app = (match_by_company(applications, ai["company"], ai["position"])
                       or match_application(applications, sender, subject, body))
                if not app:
                    if not ai["company"]:
                        continue
                    guessed_company, guessed_position = ai["company"], ai["position"]
            else:
                app = match_application(applications, sender, subject, body)
                category, status = classify(subject, body)
            if ai is None and not app:
                # discovering new applications: only emails that look like a reply about a job
                text = f"{subject} {body[:3000]}".lower()
                if category == "other" or not any(k in text for k in JOB_CONTEXT):
                    continue
                guessed_company, guessed_position = extract_company_position(sender, subject, body)
                if not guessed_company:
                    continue
            seen.add(mid)
            confidence = "high"
            if app:
                app, confidence = refine_application(
                    applications, app, f"{(ai or {}).get('position', '')} {subject} {body[:1500]}", received)
            results.append(dict(
                message_id=mid, application_id=app["id"] if app else None, sender=sender, subject=subject,
                received_at=received, snippet="", summary=(ai or {}).get("summary", ""), category=category, suggested_status=status,
                guessed_company=guessed_company, guessed_position=guessed_position,
                match_confidence=confidence, job_url=pick_job_url(_links(msg))))
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return results


def find_company_candidates(company, days=365, limit=60, known_ids=()):
    """Candidate emails for a company: a Gmail-side search (sender, subject or body), with the start of each body.

    Classifies nothing: relevance to a specific application is decided afterwards by Claude."""
    name = (company or "").replace('"', "").strip()
    if len(name) < 2:
        return []
    host = os.getenv("IMAP_HOST", "imap.gmail.com")
    user = (os.getenv("IMAP_USER") or "").strip()
    password = re.sub(r"\s+", "", os.getenv("IMAP_PASSWORD") or "")
    folder = os.getenv("IMAP_FOLDER", "INBOX")
    since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
    own, known, needle = user.lower(), set(known_ids), name.lower()
    results = []

    imap = imaplib.IMAP4_SSL(host, timeout=60)
    try:
        imap.login(user, password)
        imap.select(f'"{folder}"', readonly=True)
        picked = None
        if "gmail" in host.lower():
            try:
                query = f'newer_than:{days}d "{name}" {GMAIL_EXCLUDE}'
                imap._encoding = "utf-8"
                escaped = query.replace("\\", "\\\\").replace('"', '\\"')
                typ, data = imap.search(None, "X-GM-RAW", f'"{escaped}"')
                if typ == "OK":
                    picked = data[0].split()[-limit * 2:]
            except Exception:
                picked = None
        if picked is None:  # not Gmail: filter by headers only so the whole mailbox is not downloaded
            _, data = imap.search(None, "SINCE", since)
            nums, picked = data[0].split(), []
            for end in range(len(nums), 0, -HEADER_CHUNK):
                chunk = nums[max(0, end - HEADER_CHUNK):end]
                _, parts = imap.fetch(b",".join(chunk).decode(), HEADER_FIELDS)
                for meta, raw in _fetched_bytes(parts):
                    try:
                        hdr = email.message_from_bytes(raw)
                        text = f"{_decode(hdr.get('From'))} {_decode(hdr.get('Subject'))}".lower()
                        if needle in text:
                            picked.append(meta.split()[0])
                    except Exception:
                        continue
                if len(picked) >= limit * 2:
                    break
            picked = list(reversed(picked))  # ascending order, like a Gmail search
        for num in reversed(picked):
            if len(results) >= limit:
                break
            try:
                _, parts = imap.fetch(num.decode() if isinstance(num, bytes) else num, f"(BODY.PEEK[]<0.{BODY_LIMIT}>)")
                fetched = _fetched_bytes(parts)
                if not fetched:
                    continue
                msg = email.message_from_bytes(fetched[0][1])
                sender, subject = _decode(msg.get("From")), _decode(msg.get("Subject"))
                mid = (msg.get("Message-ID") or "").strip() or f"{sender}|{msg.get('Date')}|{subject}"
                if mid in known or (own and own in sender.lower()):
                    continue
                body = _body_text(msg)
                try:
                    received = parsedate_to_datetime(msg.get("Date"))
                    if received.tzinfo is None:
                        received = received.replace(tzinfo=timezone.utc)
                except Exception:
                    received = None
            except Exception:
                continue
            results.append(dict(message_id=mid, sender=sender, subject=subject, received_at=received, body=body,
                                job_url=pick_job_url(_links(msg))))
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return results
