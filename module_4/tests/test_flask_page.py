"""Flask app factory and Analysis page rendering."""

import pytest
from bs4 import BeautifulSoup

from src.flask_app import PULL_BUTTON_TESTID, UPDATE_BUTTON_TESTID, create_app, get_services

pytestmark = pytest.mark.web

#: Every route the application is expected to expose.
EXPECTED_ROUTES = {
    "/": {"GET"},
    "/analysis": {"GET"},
    "/pull-data": {"POST"},
    "/update-analysis": {"POST"},
    "/status": {"GET"},
}


def test_create_app_returns_testable_app(static_app):
    """The factory produces a configured, testable Flask app."""
    assert static_app.testing is True
    assert static_app.config["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert get_services(static_app) is static_app.extensions["gradcafe"]


def test_create_app_accepts_a_config_mapping():
    """Config values passed to the factory reach ``app.config``."""
    app = create_app({"TESTING": True, "MAX_CONTENT_LENGTH": 4096},
                     analysis=lambda: [], run_async=False)
    assert app.config["MAX_CONTENT_LENGTH"] == 4096


def test_create_app_honours_an_explicit_database_url():
    """An explicit ``database_url`` overrides the environment."""
    url = "postgresql+psycopg://someone@db.example:5432/other"
    app = create_app({"TESTING": True}, analysis=lambda: [], database_url=url)
    assert app.config["DATABASE_URL"] == url


def test_every_expected_route_is_registered(static_app):
    """All five routes exist with the expected methods."""
    registered = {
        rule.rule: rule.methods - {"HEAD", "OPTIONS"}
        for rule in static_app.url_map.iter_rules()
        if rule.endpoint != "static"
    }
    assert registered == EXPECTED_ROUTES


def test_root_redirects_to_analysis(static_client):
    """``GET /`` sends the browser to the analysis page."""
    response = static_client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/analysis")


def test_get_analysis_returns_200(static_client):
    """``GET /analysis`` loads successfully."""
    assert static_client.get("/analysis").status_code == 200


def test_analysis_page_has_both_buttons(static_client):
    """Both buttons render, with their stable selectors and their labels."""
    soup = BeautifulSoup(static_client.get("/analysis").data, "html.parser")

    pull = soup.find(attrs={"data-testid": PULL_BUTTON_TESTID})
    update = soup.find(attrs={"data-testid": UPDATE_BUTTON_TESTID})

    assert pull is not None and update is not None
    assert pull.name == "button" and update.name == "button"
    assert "Pull Data" in pull.get_text()
    assert "Update Analysis" in update.get_text()


def test_analysis_page_mentions_analysis_and_has_answer_labels(static_client):
    """The page says "Analysis" and carries at least one ``Answer:`` label."""
    text = BeautifulSoup(static_client.get("/analysis").data, "html.parser").get_text()
    assert "Analysis" in text
    assert text.count("Answer:") >= 1


def test_analysis_page_renders_one_card_per_question(static_client, static_app):
    """Each analysis question becomes its own card."""
    soup = BeautifulSoup(static_client.get("/analysis").data, "html.parser")
    cards = soup.select("[data-testid^='result-']")
    assert len(cards) == len(get_services(static_app).analysis())


def test_status_route_reports_idle_state(static_client):
    """``GET /status`` describes an app with no pull running."""
    body = static_client.get("/status").get_json()
    assert body["running"] is False
    assert body["last_error"] is None


def test_analysis_failure_renders_an_error_banner_not_a_crash():
    """A failing analysis provider yields a 200 page with an error banner."""
    def exploding_analysis():
        raise RuntimeError("connection refused")

    client = create_app({"TESTING": True}, analysis=exploding_analysis,
                        run_async=False).test_client()
    response = client.get("/analysis")
    soup = BeautifulSoup(response.data, "html.parser")

    assert response.status_code == 200
    assert "Could not read the analysis" in soup.find(
        attrs={"data-testid": "analysis-error"}
    ).get_text()
