"""Unit tests for the ETL helpers: cleaning, standardising and the pipeline."""

import datetime

import pytest

from src import pull_data, standardize
from src.clean import (
    POSSIBLE_SCORES,
    clean_date,
    clean_float,
    clean_int,
    clean_scraped_record,
    clean_text,
    entry_id_from_url,
)
from src.load_data import pick, to_row

pytestmark = pytest.mark.db


# ------------------------------------------------------------------- clean
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("  Stanford  ", "Stanford"),
        ("", None),
        ("N/A", None),
        ("null", None),
        ("--", None),
        (None, None),
        (42, "42"),
    ],
)
def test_clean_text(value, expected):
    """Placeholders and blanks become ``None``; everything else is stripped."""
    assert clean_text(value) == expected


@pytest.mark.parametrize(
    ("value", "field", "expected"),
    [
        (3.9, "gpa", 3.9),
        ("3.90", "gpa", 3.9),
        ("GPA 3.80", "gpa", 3.8),
        (9.2, "gpa", None),          # a 10-point scale
        ("320", "gre", None),        # a combined score
        ("168", "gre", 168.0),
        (4, "gre_aw", 4.0),
        (7.5, "gre_aw", None),
        ("no digits here", "gpa", None),
        ("", "gpa", None),
        (None, "gpa", None),
        (True, "gpa", None),         # a bool is never a score
    ],
)
def test_clean_float(value, field, expected):
    """Numbers are extracted and range-checked against the field."""
    assert clean_float(value, field) == expected


def test_possible_scores_cover_every_numeric_field():
    """Each numeric column has a declared plausible range."""
    assert set(POSSIBLE_SCORES) == {"gpa", "gre", "gre_v", "gre_aw"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1020482", 1020482), ("id 77", 77), ("none", None), (None, None), ("abc", None)],
)
def test_clean_int(value, expected):
    """Whole numbers are extracted, with ``None`` when there are no digits."""
    assert clean_int(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-09-12", datetime.date(2026, 9, 12)),
        ("Sep 12, 2026", datetime.date(2026, 9, 12)),
        ("September 12, 2026", datetime.date(2026, 9, 12)),
        ("12 September 2026", datetime.date(2026, 9, 12)),
        ("09/12/2026", datetime.date(2026, 9, 12)),
        ("Added on Sep 12, 2026", datetime.date(2026, 9, 12)),
        ("sometime last autumn", None),
        (None, None),
    ],
)
def test_clean_date(value, expected):
    """Every documented date format parses; anything else is ``None``."""
    assert clean_date(value) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.thegradcafe.com/result/1020482", 1020482),
        ("/result/7", 7),
        ("https://example.com/other", None),
        (None, None),
    ],
)
def test_entry_id_from_url(url, expected):
    """The entry id is read out of a result URL."""
    assert entry_id_from_url(url) == expected


def test_clean_scraped_record_joins_program_and_university():
    """The combined ``program`` field keeps the Module 3 shape."""
    record = clean_scraped_record(
        {"program": "Computer Science", "university": "Johns Hopkins University",
         "url": "https://www.thegradcafe.com/result/5"}
    )
    assert record["program"] == "Computer Science, Johns Hopkins University"
    assert record["entry_id"] == 5


def test_clean_scraped_record_tolerates_missing_parts():
    """A record with neither program nor university still cleans."""
    record = clean_scraped_record({"url": "https://www.thegradcafe.com/result/6"})
    assert record["program"] is None
    assert record["gpa"] is None
    assert record["entry_id"] == 6


# ------------------------------------------------------------------ to_row
def test_pick_returns_the_first_present_key():
    """``pick`` walks the candidate names in order."""
    assert pick({"b": 2}, "a", "b") == 2
    assert pick({"a": None, "b": 3}, "a", "b") == 3
    assert pick({}, "a", "b") is None


def test_to_row_accepts_a_raw_scraper_record():
    """A raw record is normalised before being mapped onto the columns."""
    row = to_row({
        "university": "Yale University",
        "program": "History",
        "degree": "PhD",
        "url": "https://www.thegradcafe.com/result/11",
        "status": "Accepted",
        "semester_start": "Fall 2026",
        "student_type": "American",
        "date_added": "Sep 01, 2026",
    })
    assert row[0] == 11
    assert row[1] == "History, Yale University"
    assert row[5] == "Accepted"


def test_to_row_accepts_an_already_cleaned_record():
    """A Module 2 shaped record maps straight through."""
    row = to_row({
        "entry_id": 12,
        "program": "Physics, MIT",
        "applicant_status": "Rejected",
        "applicant_type": "International",
        "term": "Fall 2026",
        "gre_quant": 168,
        "gre_verbal": 160,
        "date_added": "2026-09-01",
        "llm-generated-program": "Physics",
        "llm-generated-university": "Massachusetts Institute of Technology",
    })
    assert row[0] == 12
    assert row[5] == "Rejected"
    assert row[9] == 168.0
    assert row[10] == 160.0
    assert row[14] == "Massachusetts Institute of Technology"


def test_to_row_falls_back_to_the_url_for_the_id():
    """A cleaned record with no ``entry_id`` still gets one from its URL."""
    row = to_row({"entry_id": None, "url": "https://www.thegradcafe.com/result/13"})
    assert row[0] == 13


def test_to_row_returns_none_without_an_id():
    """No id anywhere means the record cannot be stored."""
    assert to_row({"entry_id": None, "url": "https://example.com/nope"}) is None


# ------------------------------------------------------------ standardize
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Computer Science, JHU", ("Computer Science", "Johns Hopkins University")),
        ("Physics, MIT", ("Physics", "Massachusetts Institute of Technology")),
        ("Statistics, CMU", ("Statistics", "Carnegie Mellon University")),
        ("Economics, Stanford", ("Economics", "Stanford University")),
        ("History, Georgetown", ("History", "Georgetown University")),
        ("Information Studies, McG", ("Information Studies", "McGill University")),
        ("Mathematics, UBC", ("Mathematics", "University of British Columbia")),
        ("Linguistics, uoft", ("Linguistics", "University of Toronto")),
    ],
)
def test_rules_standardize_expands_abbreviations(text, expected):
    """Known abbreviations expand to their canonical names."""
    assert standardize.rules_standardize(text) == expected


def test_rules_standardize_handles_at_separator():
    """``Program at University`` is split on the word ``at``."""
    prog, uni = standardize.rules_standardize("Chemistry at Yale University")
    assert prog == "Chemistry"
    assert uni == "Yale University"


def test_rules_standardize_returns_unknown_without_a_university():
    """Text naming no university yields ``Unknown``."""
    assert standardize.rules_standardize("Chemistry")[1] == "Unknown"


def test_rules_standardize_lowercases_connecting_words():
    """``Of`` and ``And`` are lowercased inside a title-cased name."""
    prog, uni = standardize.rules_standardize(
        "science and technology studies, university of utah"
    )
    assert "and" in prog
    assert uni.startswith("University of")


def test_read_lines_returns_empty_for_a_missing_file(tmp_path):
    """A missing canonical list degrades to no candidates."""
    assert standardize.read_lines(str(tmp_path / "absent.txt")) == []


def test_best_match_returns_none_without_candidates():
    """Fuzzy matching with nothing to match against returns ``None``."""
    assert standardize.best_match("Anything", [], cutoff=0.8) is None
    assert standardize.best_match("", ["Anything"], cutoff=0.8) is None


def test_best_match_finds_a_close_name():
    """A near miss snaps to the canonical spelling."""
    assert standardize.best_match(
        "Massachusetts Institute of Technlogy",
        ["Massachusetts Institute of Technology"],
        cutoff=0.86,
    ) == "Massachusetts Institute of Technology"


def test_standardize_text_prefers_the_model_when_available():
    """When a model is injected its answer is used."""
    def fake_llm(text):
        return {"standardized_program": "Modelled Program",
                "standardized_university": "Modelled University"}

    assert standardize.standardize_text("anything", call_llm=fake_llm) == (
        "Modelled Program", "Modelled University"
    )


def test_standardize_text_falls_back_when_the_model_raises():
    """A model error drops through to the rules rather than failing."""
    def broken_llm(text):
        raise RuntimeError("model not loaded")

    assert standardize.standardize_text("Physics, MIT", call_llm=broken_llm) == (
        "Physics", "Massachusetts Institute of Technology"
    )


def test_standardize_rows_adds_both_llm_keys():
    """Rows gain the two LLM fields in place."""
    rows = [{"program": "Computer Science, JHU"}, {"program": None}]
    standardize.standardize_rows(rows)
    assert rows[0]["llm-generated-university"] == "Johns Hopkins University"
    assert rows[1]["llm-generated-university"] == "Unknown"


def test_module_reports_whether_the_model_is_available():
    """``HAVE_LLM`` mirrors whether the optional model imported."""
    assert standardize.HAVE_LLM is (standardize.CALL_LLM is not None)


def test_load_llm_returns_none_without_the_dependency():
    """The optional import degrades to ``None`` in a plain environment."""
    assert standardize._load_llm() is None


# -------------------------------------------------------------- pull_data
def test_clean_records_passes_cleaned_rows_through():
    """A record that already has an ``entry_id`` is not re-cleaned."""
    already = {"entry_id": 20, "program": "Physics, MIT"}
    cleaned = pull_data.clean_records([already])
    assert cleaned[0]["entry_id"] == 20
    assert cleaned[0]["llm-generated-university"] == "Massachusetts Institute of Technology"


def test_known_urls_reads_what_is_stored(db, database_url):
    """The pipeline learns which URLs are already present."""
    db.execute(
        "INSERT INTO applicants (p_id, url) VALUES (1, 'https://example.test/result/1')"
    )
    assert pull_data.known_urls(database_url) == {"https://example.test/result/1"}


def test_pull_new_records_with_nothing_new_still_reports_the_total(db, database_url):
    """An empty scrape reports zero inserted and the current row count."""
    messages = []
    stats = pull_data.pull_new_records(
        scraper=lambda known: [],
        loader=lambda records: (0, 0, 7),
        url=database_url,
        log=messages.append,
    )
    assert stats == {"scraped": 0, "inserted": 0, "skipped": 0, "total_rows": 7}
    assert any("scraped 0" in m for m in messages)


def test_pull_new_records_cleans_and_loads(db, database_url, row_count):
    """New raw rows are cleaned, standardised and stored."""
    raw = [{
        "university": "Brown University",
        "program": "Economics",
        "degree": "PhD",
        "url": "https://www.thegradcafe.com/result/9500001",
        "status": "Accepted",
        "semester_start": "Fall 2026",
        "student_type": "American",
        "date_added": "Sep 06, 2026",
    }]
    stats = pull_data.pull_new_records(scraper=lambda known: raw, url=database_url)

    assert stats["scraped"] == 1
    assert stats["inserted"] == 1
    assert row_count() == 1


def test_pull_new_records_tells_the_scraper_what_is_known(db, database_url):
    """The scraper is handed the stored URLs so it can stop early."""
    db.execute(
        "INSERT INTO applicants (p_id, url) VALUES (2, 'https://example.test/result/2')"
    )
    seen = {}

    def scraper(known):
        seen["known"] = set(known)
        return []

    pull_data.pull_new_records(
        scraper=scraper, loader=lambda records: (0, 0, 1), url=database_url
    )
    assert seen["known"] == {"https://example.test/result/2"}


def test_pull_new_records_uses_the_real_scraper_by_default(db, database_url, monkeypatch):
    """Omitting the scraper wires in :func:`src.scrape.scrape_pages`."""
    captured = {}

    def fake_scrape_pages(known_urls, max_pages, log):
        captured["max_pages"] = max_pages
        log("fake scraper ran")
        return []

    monkeypatch.setattr(pull_data.scrape, "scrape_pages", fake_scrape_pages)
    messages = []

    pull_data.pull_new_records(url=database_url, max_pages=3, log=messages.append)

    assert captured["max_pages"] == 3
    assert "fake scraper ran" in messages
