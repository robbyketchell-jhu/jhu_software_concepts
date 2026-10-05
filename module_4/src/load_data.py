"""Load cleaned Grad Cafe rows into PostgreSQL with psycopg.

The loader is used in two places:

* as a command line tool for the bulk Module 2 dataset
  (``python -m src.load_data data.json``), and
* from :mod:`src.pull_data` for rows that the Pull Data button just scraped.

Every write is an upsert keyed on ``p_id``, so running the loader twice never
duplicates a row. That uniqueness policy is what the idempotency tests check.
"""

import json
import sys

import psycopg
from psycopg import sql

from . import config
from .clean import (
    clean_date,
    clean_float,
    clean_int,
    clean_scraped_record,
    clean_text,
    entry_id_from_url,
)

#: DDL for the required Module 3 schema.
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

#: Column order used by :func:`to_row` and the INSERT statement.
COLUMNS = [
    "p_id", "program", "comments", "date_added", "url", "status", "term",
    "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
    "llm_generated_program", "llm_generated_university",
]

#: Upsert statement: a re-scraped entry updates its own row rather than
#: creating a duplicate or failing on the primary key.
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
    """Return the first key present and non-``None`` in *record*.

    The two record shapes use different names for the same field, so callers
    list both, e.g. ``pick(record, "applicant_status", "status")``.

    :param record: the record to inspect.
    :param keys: candidate key names, in priority order.
    :returns: the first value found, or ``None``.
    """
    for key in keys:
        if key in record and record[key] is not None:
            return record[key]
    return None


def to_row(record):
    """Map one record onto the :data:`COLUMNS` tuple.

    Raw scraper records are normalised with
    :func:`src.clean.clean_scraped_record` first.

    :param record: a cleaned or raw record.
    :returns: a tuple in :data:`COLUMNS` order, or ``None`` when the record
        carries no usable ``p_id``.
    """
    if "university" in record and "entry_id" not in record:
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
    """Read a JSON array or JSON Lines file of records.

    :param path: path to the data file.
    :returns: the list of records.
    :raises json.JSONDecodeError: when the file is not valid JSON.
    """
    with open(path, encoding="utf-8") as handle:
        text = handle.read().strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def connect(url=None):
    """Open a psycopg connection to the application database.

    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: an open :class:`psycopg.Connection`.
    """
    return psycopg.connect(config.psycopg_conninfo(url))


def ensure_database(url=None):
    """Create the target database if it does not exist yet.

    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: ``True`` when a database was created.
    """
    name = config.database_name(url)
    admin = config.psycopg_conninfo(config.url_for_database("postgres", url))
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if exists:
            return False
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    return True


def ensure_table(url=None):
    """Create the ``applicants`` table if it does not exist yet.

    :param url: connection URL, defaulting to ``DATABASE_URL``.
    """
    with connect(url) as conn:
        conn.execute(CREATE_TABLE)


def load_records(records, url=None):
    """Clean and upsert *records*.

    The whole batch runs inside one transaction, so a failure leaves no
    partial writes behind.

    :param records: cleaned or raw records.
    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: a ``(upserted, skipped, total_rows)`` tuple, where *skipped*
        counts records without a usable id and *total_rows* is the row count
        of the table afterwards.
    """
    rows = {}
    skipped = 0
    for record in records:
        row = to_row(record)
        if row is None:
            skipped += 1
            continue
        rows[row[0]] = row  # dedupe within the batch; later entries win

    with connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE)
            if rows:
                cur.executemany(INSERT, list(rows.values()))
            total = cur.execute("SELECT COUNT(*) FROM applicants").fetchone()[0]
    return len(rows), skipped, total


def main(argv=None):
    """Command line entry point.

    :param argv: argument list, defaulting to :data:`sys.argv` minus the
        program name. The first argument is the data file to load.
    :returns: a process exit code.
    """
    config.load_environment()
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("Usage: python -m src.load_data <data-file.json>", file=sys.stderr)
        return 1
    path = argv[0]

    try:
        records = read_records(path)
    except FileNotFoundError:
        print(f"Data file not found: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"Could not parse {path}: {exc}", file=sys.stderr)
        return 1

    try:
        ensure_database()
        upserted, skipped, total = load_records(records)
    except psycopg.OperationalError as exc:
        print(f"Could not connect to PostgreSQL: {exc}", file=sys.stderr)
        print("Check DATABASE_URL (or the DB_* variables).", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"Database error: {exc}", file=sys.stderr)
        return 1

    print(f"Read {len(records)} records from {path}")
    print(f"Upserted {upserted} unique applicants ({skipped} skipped without an id)")
    print(f"applicants table now has {total} rows")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
