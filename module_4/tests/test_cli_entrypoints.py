"""Command line entry points and the remaining loader helpers."""

import json

import psycopg
import pytest

from src import config, load_data, pull_data
from src.flask_app import create_app, get_services

pytestmark = pytest.mark.db


# ------------------------------------------------------------ read_records
def test_read_records_parses_a_json_array(tmp_path):
    """A JSON array file is read as a list of records."""
    path = tmp_path / "records.json"
    path.write_text(json.dumps([{"entry_id": 1}, {"entry_id": 2}]))
    assert load_data.read_records(str(path)) == [{"entry_id": 1}, {"entry_id": 2}]


def test_read_records_parses_json_lines(tmp_path):
    """A JSON Lines file is read one record per line, blanks skipped."""
    path = tmp_path / "records.jsonl"
    path.write_text('{"entry_id": 1}\n\n{"entry_id": 2}\n')
    assert load_data.read_records(str(path)) == [{"entry_id": 1}, {"entry_id": 2}]


# --------------------------------------------------------- ensure_database
def test_ensure_database_creates_a_missing_database(database_url):
    """A database that does not exist yet is created, then reported as present."""
    scratch_url = config.url_for_database("gradcafe_scratch_test", database_url)
    admin = config.psycopg_conninfo(config.url_for_database("postgres", database_url))

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS gradcafe_scratch_test")
    try:
        assert load_data.ensure_database(scratch_url) is True
        assert load_data.ensure_database(scratch_url) is False
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute("DROP DATABASE IF EXISTS gradcafe_scratch_test")


# ---------------------------------------------------- load_data entry point
def test_load_data_main_without_arguments_prints_usage(capsys):
    """No data file is an error with a usage line."""
    assert load_data.main([]) == 1
    assert "Usage" in capsys.readouterr().err


def test_load_data_main_reports_a_missing_file(capsys):
    """A path that does not exist is reported, not raised."""
    assert load_data.main(["/nonexistent/path/records.json"]) == 1
    assert "Data file not found" in capsys.readouterr().err


def test_load_data_main_reports_bad_json(tmp_path, capsys):
    """Malformed JSON is reported with the parser's message."""
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    assert load_data.main([str(path)]) == 1
    assert "Could not parse" in capsys.readouterr().err


def test_load_data_main_loads_a_file(db, row_count, tmp_path, capsys):
    """A well-formed file is loaded and the counts are reported."""
    path = tmp_path / "records.json"
    path.write_text(json.dumps([{
        "entry_id": 7700001,
        "program": "Physics, MIT",
        "applicant_status": "Accepted",
        "term": "Fall 2026",
        "applicant_type": "American",
        "date_added": "2026-09-01",
        "url": "https://www.thegradcafe.com/result/7700001",
    }]))

    assert load_data.main([str(path)]) == 0

    output = capsys.readouterr().out
    assert "Read 1 records" in output
    assert "Upserted 1 unique applicants" in output
    assert row_count() == 1


def test_load_data_main_reports_a_connection_failure(monkeypatch, tmp_path, capsys):
    """An unreachable database is reported rather than raised."""
    path = tmp_path / "records.json"
    path.write_text("[]")

    def boom(*args, **kwargs):
        raise psycopg.OperationalError("could not connect")

    monkeypatch.setattr(load_data, "ensure_database", boom)
    assert load_data.main([str(path)]) == 1
    assert "Could not connect to PostgreSQL" in capsys.readouterr().err


def test_load_data_main_reports_a_database_error(monkeypatch, tmp_path, capsys):
    """Any other database error is reported with its message."""
    path = tmp_path / "records.json"
    path.write_text("[]")

    def boom(*args, **kwargs):
        raise psycopg.ProgrammingError("relation does not exist")

    monkeypatch.setattr(load_data, "ensure_database", boom)
    assert load_data.main([str(path)]) == 1
    assert "Database error" in capsys.readouterr().err


# ---------------------------------------------------- pull_data entry point
def test_pull_data_main_reports_the_statistics(monkeypatch, capsys):
    """A successful pull prints what it stored."""
    monkeypatch.setattr(
        pull_data, "pull_new_records",
        lambda **kwargs: {"scraped": 3, "inserted": 3, "skipped": 0, "total_rows": 12},
    )
    assert pull_data.main([]) == 0
    output = capsys.readouterr().out
    assert "3 scraped" in output
    assert "12 rows in total" in output


def test_pull_data_main_honours_max_pages(monkeypatch):
    """``--max-pages`` is forwarded to the pipeline."""
    captured = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return {"scraped": 0, "inserted": 0, "skipped": 0, "total_rows": 0}

    monkeypatch.setattr(pull_data, "pull_new_records", fake)
    assert pull_data.main(["--max-pages", "4"]) == 0
    assert captured["max_pages"] == 4


def test_pull_data_main_logs_progress(monkeypatch, capsys):
    """The pipeline's log messages reach the console."""
    def fake(**kwargs):
        kwargs["log"]("walking page 1")
        return {"scraped": 0, "inserted": 0, "skipped": 0, "total_rows": 0}

    monkeypatch.setattr(pull_data, "pull_new_records", fake)
    pull_data.main([])
    assert "walking page 1" in capsys.readouterr().out


def test_pull_data_main_reports_a_scrape_failure(monkeypatch, capsys):
    """A scraper error is reported and the exit code is non-zero."""
    def boom(**kwargs):
        raise pull_data.scrape.ScrapeError("Cloudflare challenge")

    monkeypatch.setattr(pull_data, "pull_new_records", boom)
    assert pull_data.main([]) == 1
    assert "Pull failed: Cloudflare challenge" in capsys.readouterr().err


def test_pull_data_main_reports_an_os_error(monkeypatch, capsys):
    """A filesystem or socket error is reported the same way."""
    def boom(**kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(pull_data, "pull_new_records", boom)
    assert pull_data.main([]) == 1
    assert "Pull failed" in capsys.readouterr().err


# ------------------------------------------------------------- app factory
@pytest.mark.web
def test_create_app_without_a_config_mapping():
    """The factory works with no config argument at all."""
    app = create_app(analysis=lambda: [], run_async=False)
    assert app.config["TESTING"] is False
    assert get_services(app).run_async is False
    assert app.config["DATABASE_URL"].startswith("postgresql+psycopg://")


@pytest.mark.web
def test_create_app_defaults_to_running_pulls_asynchronously():
    """Outside tests a pull runs on a background thread."""
    app = create_app(analysis=lambda: [])
    assert get_services(app).run_async is True
