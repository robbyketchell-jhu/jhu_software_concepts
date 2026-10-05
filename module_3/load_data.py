"""
Module 3 - load_data.py

Loads the cleaned Module 2 applicant data into the PostgreSQL `applicants` table.
The source file is the LLM-extended dataset that was posted on Teams
(llm_extend_applicant_data_clean.json). The same code path is reused by
pull_data.py to insert freshly scraped rows, so the loader also understands the
raw scrape.py record shape (see clean.py).

Usage:
    python load_data.py                      # loads DATA_FILE from .env (default below)
    python load_data.py some_other_file.json

Running it twice is safe: rows are upserted on p_id, so nothing is duplicated.

Connection settings come from environment variables (loaded from a gitignored
.env file): DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT.
"""

import json
import os
import sys

import psycopg
from psycopg import sql
from dotenv import load_dotenv  # This is for loading the environment variables for the database

from clean import (
    clean_date,
    clean_float,
    clean_int,
    clean_scraped_record,
    clean_text,
    entry_id_from_url,
)

load_dotenv()  # Loads all those env variables

DB_NAME = os.getenv("DB_NAME", "module_3")
DATA_FILE = os.getenv("DATA_FILE", "llm_extend_applicant_data_clean.json")  # Path to the data source file

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS applicants (
    p_id                     INTEGER PRIMARY KEY,
    program                  TEXT,
    comments                 TEXT,
    date_added               DATE,
    url                      TEXT,
    status                   TEXT,
    term                     TEXT,
    us_or_international      TEXT,
    gpa                      FLOAT,
    gre                      FLOAT,
    gre_v                    FLOAT,
    gre_aw                   FLOAT,
    degree                   TEXT,
    llm_generated_program    TEXT,
    llm_generated_university TEXT
);
"""

COLUMNS = [
    "p_id", "program", "comments", "date_added", "url", "status", "term",
    "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
    "llm_generated_program", "llm_generated_university",
]

# Upsert: a second run (or a Pull Data run that re-scrapes an entry) updates the
# existing row instead of creating a duplicate or crashing on the primary key.
INSERT = sql.SQL(
    "INSERT INTO applicants ({cols}) VALUES ({vals}) "
    "ON CONFLICT (p_id) DO UPDATE SET {updates}"
).format(
    cols=sql.SQL(", ").join(sql.Identifier(c) for c in COLUMNS),
    vals=sql.SQL(", ").join(sql.Placeholder() for _ in COLUMNS),
    updates=sql.SQL(", ").join(
        sql.SQL("{c} = EXCLUDED.{c}").format(c=sql.Identifier(c)) for c in COLUMNS[1:]
    ),
)


def pick(record, *keys):
    """First key that is present in the record (the two data shapes use different names)."""
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def to_row(record):
    """
    Maps one cleaned record onto the applicants columns, in COLUMNS order.
    Returns None when there is no usable id, since p_id is the primary key.
    """
    if "university" in record and "entry_id" not in record:
        # Raw scrape.py shape: normalise it first.
        record = clean_scraped_record(record)

    p_id = clean_int(pick(record, "entry_id", "p_id")) or entry_id_from_url(record.get("url"))
    if p_id is None:
        return None

    return (
        p_id,
        clean_text(record.get("program")),
        clean_text(record.get("comments")),
        clean_date(record.get("date_added")),
        clean_text(record.get("url")),
        clean_text(pick(record, "applicant_status", "status")),
        clean_text(record.get("term")),
        clean_text(pick(record, "applicant_type", "us_or_international")),
        clean_float(record.get("gpa"), "gpa"),
        clean_float(pick(record, "gre_quant", "gre"), "gre"),
        clean_float(pick(record, "gre_verbal", "gre_v"), "gre_v"),
        clean_float(record.get("gre_aw"), "gre_aw"),
        clean_text(record.get("degree")),
        clean_text(pick(record, "llm-generated-program", "llm_generated_program")),
        clean_text(pick(record, "llm-generated-university", "llm_generated_university")),
    )


def read_records(path):
    """Reads the file and returns the list of records (JSON array or JSON Lines)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    text = text.strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def conninfo(dbname=None):
    """
    Nice little function that returns the connection info in the psycopg object that it requires.
    All of these values are stored in an environment file called .env and gitignored.
    """
    return psycopg.conninfo.make_conninfo(
        dbname=dbname or DB_NAME,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )


def ensure_database():
    """Create the target database if it doesn't exist yet."""
    with psycopg.connect(conninfo("postgres"), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            print(f"Created database {DB_NAME}")


def load_records(records):
    """
    Cleans and upserts a list of records. Returns (upserted, skipped, total_rows).
    Shared by the bulk load below and by pull_data.py.
    """
    rows = {}
    skipped = 0
    for record in records:
        row = to_row(record)
        if row is None:
            skipped += 1
            continue
        rows[row[0]] = row  # dedupe within the batch; later entries win

    ensure_database()
    with psycopg.connect(conninfo()) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE)
            if rows:
                cur.executemany(INSERT, list(rows.values()))
            total = cur.execute("SELECT COUNT(*) FROM applicants").fetchone()[0]
        # The connection context manager commits on success, rolls back on error.
    return len(rows), skipped, total


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DATA_FILE
    try:
        records = read_records(path)
    except FileNotFoundError:
        print(f"Data file not found: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Could not parse {path}: {exc}", file=sys.stderr)
        return 1

    try:
        upserted, skipped, total = load_records(records)
    except psycopg.OperationalError as exc:
        print(f"Could not connect to PostgreSQL: {exc}", file=sys.stderr)
        print("Check DB_NAME / DB_USER / DB_PASSWORD / DB_HOST / DB_PORT in .env", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 1

    print(f"Read {len(records)} records from {path}")
    print(f"Upserted {upserted} unique applicants ({skipped} skipped without an id)")
    print(f"applicants table now has {total} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
