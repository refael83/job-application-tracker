import os

import psycopg
import psycopg.sql
from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

DB_NAME = os.getenv("PGDATABASE", "job_tracker")


def _conninfo(dbname):
    return dict(
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
        dbname=dbname,
    )


def connect():
    return psycopg.connect(**_conninfo(DB_NAME), row_factory=dict_row)


SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    id SERIAL PRIMARY KEY,
    company TEXT NOT NULL,
    position TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    applied_date DATE,
    status TEXT NOT NULL DEFAULT 'הוגשה',
    resume_version TEXT NOT NULL DEFAULT '',
    contact TEXT NOT NULL DEFAULT '',
    salary TEXT NOT NULL DEFAULT '',
    follow_up_date DATE,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    application_id INT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS email_suggestions (
    id SERIAL PRIMARY KEY,
    message_id TEXT NOT NULL UNIQUE,
    application_id INT REFERENCES applications(id) ON DELETE CASCADE,
    sender TEXT NOT NULL DEFAULT '',
    subject TEXT NOT NULL DEFAULT '',
    received_at TIMESTAMPTZ,
    snippet TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    suggested_status TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE email_suggestions ADD COLUMN IF NOT EXISTS guessed_company TEXT;
ALTER TABLE email_suggestions ADD COLUMN IF NOT EXISTS guessed_position TEXT;
ALTER TABLE email_suggestions ADD COLUMN IF NOT EXISTS summary TEXT NOT NULL DEFAULT '';
ALTER TABLE email_suggestions ADD COLUMN IF NOT EXISTS match_confidence TEXT NOT NULL DEFAULT 'high';
ALTER TABLE email_suggestions ADD COLUMN IF NOT EXISTS job_url TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS scan_runs (
    id SERIAL PRIMARY KEY,
    ran_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    days INT NOT NULL,
    scanned_new INT NOT NULL DEFAULT 0,
    linked INT NOT NULL DEFAULT 0,
    needs_review INT NOT NULL DEFAULT 0,
    discovered INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_app ON events(application_id);
"""


def init_db():
    """Create the database (if missing) and its tables."""
    with psycopg.connect(**_conninfo("postgres"), autocommit=True) as admin:
        exists = admin.execute("SELECT 1 FROM pg_database WHERE datname=%s", (DB_NAME,)).fetchone()
        if not exists:
            admin.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(DB_NAME)))
    with connect() as conn:
        conn.execute(SCHEMA)
