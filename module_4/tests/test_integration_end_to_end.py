"""End-to-end flows: pull, update, render."""

import re

import pytest
from bs4 import BeautifulSoup

from src.flask_app import create_app, get_services
from src.query_data import REQUIRED_FIELDS, fetch_applicants

from conftest import FAKE_SCRAPED_ROWS, FakeScraper

pytestmark = pytest.mark.integration

TWO_DECIMAL_PERCENT = re.compile(r"^\d[\d,]*\.\d{2}\s*%$")
ANY_PERCENT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*%")


def page_soup(client):
    """Fetch the analysis page and parse it."""
    response = client.get("/analysis")
    assert response.status_code == 200
    return BeautifulSoup(response.data, "html.parser")


def test_pull_then_update_then_render(client, app, db, row_count, database_url):
    """The full flow: a fake scraper's rows reach the database and the page."""
    # 1. Start from an empty table and an idle app.
    assert row_count() == 0
    assert get_services(app).state.running is False

    # 2. Pull: the injected scraper returns four records and they are stored.
    pull = client.post("/pull-data")
    assert pull.status_code == 202
    assert pull.get_json()["ok"] is True
    assert row_count() == 4

    stored = fetch_applicants(limit=10, url=database_url)
    assert {r["p_id"] for r in stored} == {9000001, 9000002, 9000003, 9000004}
    assert all(set(r) == set(REQUIRED_FIELDS) for r in stored)

    # 3. Update: succeeds because no pull is running, and recomputes.
    before = get_services(app).state.analysis_version
    update = client.post("/update-analysis")
    assert update.status_code == 200
    assert update.get_json()["ok"] is True
    assert get_services(app).state.analysis_version == before + 1

    # 4. Render: the page shows the updated numbers, correctly formatted.
    soup = page_soup(client)
    text = soup.get_text(" ")
    assert "Answer:" in text

    # Two of the four fake rows are Fall 2026 entries.
    fall_2026 = soup.find(attrs={"data-testid": "result-1"})
    assert "2" in fall_2026.find(attrs={"data-testid": "answer-value"}).get_text()

    percents = ANY_PERCENT.findall(text)
    assert percents
    assert all(TWO_DECIMAL_PERCENT.match(p.strip()) for p in percents), percents


def test_two_pulls_with_overlapping_data_stay_consistent(client, db, row_count):
    """Overlapping pulls respect the ``p_id`` uniqueness policy."""
    client.post("/pull-data")
    assert row_count() == 4

    second = client.post("/pull-data")

    assert second.status_code == 202
    assert row_count() == 4
    assert second.get_json()["result"]["scraped"] == 0


def test_a_second_pull_adds_only_genuinely_new_rows(db, row_count, database_url):
    """A later pull that sees one extra entry adds exactly that one row."""
    extra = {
        "university": "Princeton University",
        "program": "Mathematics",
        "degree": "PhD",
        "date_added": "Sep 13, 2026",
        "url": "https://www.thegradcafe.com/result/9000005",
        "status": "Accepted",
        "semester_start": "Fall 2026",
        "student_type": "International",
        "gre": "169",
        "gre_v": "160",
        "gre_aw": "4.0",
        "gpa": "3.88",
        "comments": None,
    }
    scraper = FakeScraper(rows=FAKE_SCRAPED_ROWS + [extra])
    app = create_app({"TESTING": True}, scraper=scraper, run_async=False,
                     database_url=database_url)
    client = app.test_client()

    client.post("/pull-data")
    assert row_count() == 5

    second = client.post("/pull-data")

    assert second.get_json()["result"]["scraped"] == 0
    assert row_count() == 5
    # The scraper was told about every stored URL, so it could skip them.
    assert len(scraper.last_known) == 5


def test_update_is_refused_mid_pull_and_the_pull_is_untouched(client, app, db, row_count):
    """A pull in flight blocks the update without losing the pull's state."""
    client.post("/pull-data")
    assert row_count() == 4

    state = get_services(app).state
    assert state.begin() is True  # simulate a second pull now running

    refused = client.post("/update-analysis")
    assert refused.status_code == 409
    assert refused.get_json()["busy"] is True

    # The page still renders, and still reports the running pull.
    soup = page_soup(client)
    assert soup.find(attrs={"data-testid": "job-status"}) is not None
    assert state.running is True

    state.finish(result={"scraped": 0})
    assert client.post("/update-analysis").status_code == 200


def test_analysis_reflects_the_rows_that_were_pulled(client, db):
    """Numbers on the page are computed from the rows the pull inserted."""
    client.post("/pull-data")
    soup = page_soup(client)

    def answer(number):
        card = soup.find(attrs={"data-testid": f"result-{number}"})
        return card.find(attrs={"data-testid": "answer-value"}).get_text(strip=True)

    # Fake data: 2 of 4 entries are Fall 2026; 2 of 4 applicants are international.
    assert answer(1) == "2"
    assert answer(2) == "50.00%"
    # Fall 2025 rows: one acceptance out of two entries.
    assert answer(5) == "50.00%"


def test_empty_database_renders_without_errors(client, db):
    """With no rows at all the page still renders and shows N/A averages."""
    soup = page_soup(client)
    text = soup.get_text(" ")

    assert soup.find(attrs={"data-testid": "analysis-error"}) is None
    assert "Answer:" in text
    assert "N/A" in text
