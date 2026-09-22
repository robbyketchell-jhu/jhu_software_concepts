"""
The first requirement is to load the data from Module 2 into the database in the 
specified structure. I have downloaded the llm cleaned dataset from Teams that Liv posted,
and I am using that as the source to load into the database.
"""

import json
import os
import re
import sys
from datetime import date, datetime

import psycopg
from psycopg import sql
from dotenv import load_dotenv # This is for loading the environment variables for the database

load_dotenv() # Loads all those env variables

DB_NAME = os.getenv("DB_NAME", "module_3")
DATA_FILE = os.getenv("DATA_FILE", "llm_extend_applicant_data_clean.json") # Path to the data source file

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

MISSING_DATA_VALUES = {"", "n/a", "na", "NA", "None", "none", "Null", "null", "NAN", "nan", "-"}

DATE_FORMATS = ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y"]

# Plausible ranges; anything outside is treated as missing rather than stored.
POSSIBLE_SCORES = {
    "gpa": (0.0, 4.0),
    "gre": (0, 1000), # Guessing on values here
    "gre_v": (0, 1000),
    "gre_aw": (0.0, 10.0),
}


def clean_text(value):
    """
    Simple function that replaces the missing data with None.
    The first check just checks if it is None, then returns None
    Else it strips the whitespace, converts to lowercase, and returns None if there is a
    match with any of the values in MISSING_DATA_VALUES, otherwise it returns the value/text.
    """
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in MISSING_DATA_VALUES else text


def clean_float(value, field):
    """Pull a number out of values like 3.8, '3.80', or 'GPA 3.80'."""
    text = clean_text(value)
    if text is None:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    number = float(match.group())
    low, high = POSSIBLE_SCORES[field]
    return number if low <= number <= high else None


def clean_date(value):
    text = clean_text(value)
    if text is None:
        return None
    text = re.sub(r"^added on\s*", "", text, flags=re.IGNORECASE)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def to_row(record):
    return (
        p_id,
        clean_text(record[key]),
        clean_text(record[key]),
        clean_date(record[key]),
        clean_text(record[key]),
        clean_text(record[key]),
        clean_text(record[key]),
        clean_text(record[key]),
        clean_float(record[key]),
        clean_float(record[key]),
        clean_float(record[key]),
        clean_float(record[key]),
        clean_text(record[key]),
        clean_text(record[key]),
        clean_text(record[key]),
    )


def read_records(path):
    """Reads the file, returns the data as json"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def conninfo(dbname):
    """
    Nice little function that returns the connection info in the psycopg object that it requires.
    All of these values are stored in an environment file called .env and gitignores.
    """
    return psycopg.conninfo.make_conninfo(
        dbname=dbname,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )


def ensure_database():
    """Creat the target database if it doesn't exist yet. I named this db 'module_3'."""
    with psycopg.connect(conninfo("postgres"), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,)
        ).fetchone()
        if not exists:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(DB_NAME)))
            print(f"Created database {DB_NAME}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DATA_FILE
    records = read_records(path)

    # Deduplicate within the file too; later entries win.
    rows = {}
    skipped = 0
    for record in records:
        row = to_row(record)
        if row is None:
            skipped += 1
            continue
        rows[row[0]] = row

    ensure_database()
    with psycopg.connect(conninfo(DB_NAME)) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE)
            cur.executemany(INSERT, list(rows.values()))
            total = cur.execute("SELECT COUNT(*) FROM applicants").fetchone()[0]
        # The connection context manager commits on success, rolls back on error.

    print(f"Read {len(records)} records from {path}")
    print(f"Upserted {len(rows)} unique applicants ({skipped} skipped without an id)")
    print(f"applicants table now has {total} rows")


if __name__ == "__main__":
    main()