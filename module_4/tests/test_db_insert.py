"""Database schema, inserts, idempotency and the simple query function."""

import datetime

import psycopg
import pytest

from src import config, load_data
from src.query_data import REQUIRED_FIELDS, fetch_applicant, fetch_applicants

pytestmark = pytest.mark.db

#: Columns the Module 3 schema requires, with their PostgreSQL types.
EXPECTED_SCHEMA = {
    "p_id": "integer",
    "program": "text",
    "comments": "text",
    "date_added": "date",
    "url": "text",
    "status": "text",
    "term": "text",
    "us_or_international": "text",
    "gpa": "double precision",
    "gre": "double precision",
    "gre_v": "double precision",
    "gre_aw": "double precision",
    "degree": "text",
    "llm_generated_program": "text",
    "llm_generated_university": "text",
}

#: Fields that must never be null on a row written by a pull.
NON_NULL_AFTER_PULL = ("p_id", "program", "url", "status", "term", "degree",
                       "date_added", "us_or_international")


# ----------------------------------------------------------------- schema
def test_applicants_table_matches_the_required_schema(db):
    """The table has exactly the Module 3 columns, with the right types."""
    rows = db.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = 'applicants'"
    ).fetchall()
    assert dict(rows) == EXPECTED_SCHEMA


def test_p_id_is_the_primary_key(db):
    """``p_id`` is the primary key, which is what makes upserts safe."""
    rows = db.execute(
        "SELECT a.attname FROM pg_index i "
        "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
        "WHERE i.indrelid = 'applicants'::regclass AND i.indisprimary"
    ).fetchall()
    assert [r[0] for r in rows] == ["p_id"]


# ------------------------------------------------------------- insert path
def test_table_starts_empty(db, row_count):
    """The fixture hands every test an empty table."""
    assert row_count() == 0


def test_pull_inserts_rows_with_required_non_null_fields(client, db, row_count):
    """After a pull the new rows exist and their required fields are set."""
    assert row_count() == 0

    assert client.post("/pull-data").status_code == 202

    assert row_count() == 4
    columns = ", ".join(NON_NULL_AFTER_PULL)
    rows = db.execute(f"SELECT {columns} FROM applicants ORDER BY p_id").fetchall()
    assert len(rows) == 4
    for row in rows:
        assert all(value is not None for value in row), row


def test_pull_stores_correctly_typed_values(client, db):
    """Dates, floats and text land in the right PostgreSQL types."""
    client.post("/pull-data")
    row = db.execute(
        "SELECT p_id, date_added, gpa, gre, program, llm_generated_university "
        "FROM applicants WHERE p_id = 9000001"
    ).fetchone()

    p_id, date_added, gpa, gre, program, university = row
    assert p_id == 9000001
    assert date_added == datetime.date(2026, 9, 12)
    assert gpa == pytest.approx(3.90)
    assert gre == pytest.approx(168.0)
    assert "Johns Hopkins University" in program
    assert university == "Johns Hopkins University"


def test_out_of_range_scores_are_stored_as_null(db, database_url):
    """A combined GRE score is rejected rather than poisoning the averages."""
    load_data.load_records(
        [{
            "university": "Example University",
            "program": "Physics",
            "degree": "PhD",
            "url": "https://www.thegradcafe.com/result/9100001",
            "status": "Accepted",
            "semester_start": "Fall 2026",
            "student_type": "American",
            "date_added": "Sep 01, 2026",
            "gre": "320",     # combined score, not a Quantitative score
            "gpa": "9.2",     # a 10-point scale
        }],
        url=database_url,
    )
    gre, gpa = db.execute(
        "SELECT gre, gpa FROM applicants WHERE p_id = 9100001"
    ).fetchone()
    assert gre is None
    assert gpa is None


def test_records_without_an_id_are_skipped_not_inserted(db, database_url, row_count):
    """A record with no id and no result URL cannot be stored."""
    inserted, skipped, total = load_data.load_records(
        [{"university": "Nowhere", "program": "Unknown", "url": "https://example.com/x"}],
        url=database_url,
    )
    assert (inserted, skipped, total) == (0, 1, 0)
    assert row_count() == 0


# -------------------------------------------------------------- uniqueness
def test_duplicate_pulls_do_not_duplicate_rows(client, db, row_count):
    """Pulling the same data twice leaves the row count unchanged."""
    client.post("/pull-data")
    assert row_count() == 4

    client.post("/pull-data")

    assert row_count() == 4
    ids = [r[0] for r in db.execute("SELECT p_id FROM applicants ORDER BY p_id")]
    assert ids == [9000001, 9000002, 9000003, 9000004]


def test_loading_the_same_batch_twice_is_idempotent(db, database_url, row_count):
    """Calling the loader directly twice is also idempotent."""
    batch = [{
        "university": "Yale University",
        "program": "History",
        "degree": "PhD",
        "url": "https://www.thegradcafe.com/result/9200001",
        "status": "Rejected",
        "semester_start": "Fall 2026",
        "student_type": "American",
        "date_added": "Sep 03, 2026",
    }]
    load_data.load_records(batch, url=database_url)
    load_data.load_records(batch, url=database_url)
    assert row_count() == 1


def test_a_re_scraped_row_updates_in_place(db, database_url):
    """The same ``p_id`` with new values updates rather than duplicating."""
    base = {
        "university": "Brown University",
        "program": "Economics",
        "degree": "PhD",
        "url": "https://www.thegradcafe.com/result/9300001",
        "status": "Wait listed",
        "semester_start": "Fall 2026",
        "student_type": "International",
        "date_added": "Sep 04, 2026",
    }
    load_data.load_records([base], url=database_url)
    load_data.load_records([{**base, "status": "Accepted"}], url=database_url)

    rows = db.execute(
        "SELECT status FROM applicants WHERE p_id = 9300001"
    ).fetchall()
    assert rows == [("Accepted",)]


def test_a_batch_containing_the_same_id_twice_stores_one_row(db, database_url, row_count):
    """Duplicates inside one batch collapse before the insert runs."""
    row = {
        "university": "Duke University",
        "program": "Statistics",
        "degree": "Masters",
        "url": "https://www.thegradcafe.com/result/9400001",
        "status": "Accepted",
        "semester_start": "Fall 2026",
        "student_type": "American",
        "date_added": "Sep 05, 2026",
    }
    inserted, _, total = load_data.load_records([row, dict(row)], url=database_url)
    assert inserted == 1
    assert total == 1
    assert row_count() == 1


# ---------------------------------------------------- simple query function
def test_fetch_applicant_returns_a_dict_of_required_fields(db, client, database_url):
    """The query function returns exactly the required Module 3 keys."""
    client.post("/pull-data")

    record = fetch_applicant(9000001, url=database_url)

    assert isinstance(record, dict)
    assert set(record) == set(REQUIRED_FIELDS)
    assert record["p_id"] == 9000001
    assert record["status"] == "Accepted"
    assert record["term"] == "Fall 2026"
    assert record["us_or_international"] == "American"


def test_fetch_applicant_returns_none_when_missing(db, database_url):
    """An unknown id yields ``None`` rather than raising."""
    assert fetch_applicant(123456789, url=database_url) is None


def test_fetch_applicants_returns_dicts_with_required_keys(db, client, database_url):
    """The list form returns the same keys for every row."""
    client.post("/pull-data")

    records = fetch_applicants(limit=10, url=database_url)

    assert len(records) == 4
    assert all(set(r) == set(REQUIRED_FIELDS) for r in records)
    assert [r["p_id"] for r in records] == [9000004, 9000003, 9000002, 9000001]


def test_fetch_applicants_honours_the_limit(db, client, database_url):
    """The limit is applied in SQL."""
    client.post("/pull-data")
    assert len(fetch_applicants(limit=2, url=database_url)) == 2


# ------------------------------------------------------------- connections
def test_ensure_database_is_idempotent(database_url):
    """Creating a database that already exists reports no change."""
    assert load_data.ensure_database(database_url) is False


def test_ensure_table_is_idempotent(database_url, db):
    """Creating the table twice is harmless."""
    load_data.ensure_table(database_url)
    load_data.ensure_table(database_url)
    assert db.execute("SELECT to_regclass('applicants')").fetchone()[0] == "applicants"


def test_connect_uses_the_configured_url(database_url):
    """``connect`` reaches the test database, not the development one."""
    with load_data.connect(database_url) as conn:
        name = conn.execute("SELECT current_database()").fetchone()[0]
    assert name == config.database_name(database_url)


def test_connect_rejects_an_unreachable_database():
    """A bad URL surfaces as a psycopg operational error."""
    with pytest.raises(psycopg.OperationalError):
        load_data.connect("postgresql+psycopg://nobody@127.0.0.1:1/none")
