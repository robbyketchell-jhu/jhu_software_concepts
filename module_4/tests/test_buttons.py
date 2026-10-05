"""Button endpoints and busy-state gating.

Busy state is never simulated with a sleep. :class:`src.flask_app.PullState`
is observable and directly controllable, so a test flips it and asserts on
the response.
"""

import pytest

from src.flask_app import create_app, get_services

pytestmark = pytest.mark.buttons


# ------------------------------------------------------------- pull data
def test_pull_data_returns_ok_when_not_busy(client):
    """``POST /pull-data`` is accepted and reports success."""
    response = client.post("/pull-data")
    assert response.status_code == 202
    assert response.get_json()["ok"] is True


def test_pull_data_triggers_the_loader_with_scraped_rows(client, app, db):
    """The route runs the scraper and hands its rows to the loader."""
    scraper = app.config["FAKE_SCRAPER"]
    loader = app.config["RECORDING_LOADER"]

    client.post("/pull-data")

    assert scraper.calls == 1
    assert loader.calls == 1
    assert len(loader.last_records) == len(scraper.rows)
    # The loader receives cleaned rows, keyed the way the loader expects.
    assert {r["entry_id"] for r in loader.last_records} == {9000001, 9000002, 9000003, 9000004}


def test_pull_data_reports_the_pipeline_result(client, db):
    """The response body carries the pipeline's own statistics."""
    result = client.post("/pull-data").get_json()["result"]
    assert result["scraped"] == 4
    assert result["inserted"] == 4
    assert result["total_rows"] == 4


def test_pull_data_clears_busy_when_it_finishes(client, app, db):
    """The busy flag is released once a synchronous pull completes."""
    client.post("/pull-data")
    state = get_services(app).state
    assert state.running is False
    assert state.finished_at is not None


# -------------------------------------------------------- update analysis
def test_update_analysis_returns_200_when_not_busy(static_client):
    """``POST /update-analysis`` succeeds when no pull is running."""
    response = static_client.post("/update-analysis")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_update_analysis_recomputes_the_analysis(static_client, static_app):
    """A successful update bumps the observable analysis version."""
    state = get_services(static_app).state
    before = state.analysis_version

    body = static_client.post("/update-analysis").get_json()

    assert state.analysis_version == before + 1
    assert body["analysis_version"] == state.analysis_version
    assert body["questions"] == 4


def test_update_analysis_does_not_start_a_scrape(static_client, static_app):
    """Updating the analysis never invokes the scraper."""
    scraper = get_services(static_app).scraper
    static_client.post("/update-analysis")
    assert scraper.calls == 0


# ------------------------------------------------------------ busy gating
def test_update_analysis_is_409_and_performs_no_update_while_busy(static_client, static_app):
    """While a pull runs, the update is refused and nothing is recomputed."""
    state = get_services(static_app).state
    assert state.begin() is True
    before = state.analysis_version

    response = static_client.post("/update-analysis")

    assert response.status_code == 409
    assert response.get_json()["busy"] is True
    assert state.analysis_version == before  # no update was performed


def test_pull_data_is_409_while_a_pull_is_already_running(static_client, static_app):
    """A second Pull Data request is refused rather than queued."""
    services = get_services(static_app)
    assert services.state.begin() is True

    response = static_client.post("/pull-data")

    assert response.status_code == 409
    assert response.get_json()["busy"] is True
    assert services.scraper.calls == 0  # the pipeline never ran


def test_begin_is_atomic(static_app):
    """``PullState.begin`` hands the slot to exactly one caller."""
    state = get_services(static_app).state
    assert state.begin() is True
    assert state.begin() is False
    state.finish(result={"scraped": 0})
    assert state.begin() is True


def test_status_route_exposes_the_busy_flag(static_client, static_app):
    """``GET /status`` reflects the busy state without changing it."""
    get_services(static_app).state.begin()
    assert static_client.get("/status").get_json()["running"] is True


# ------------------------------------------------------------ error paths
def test_loader_failure_returns_500_and_writes_nothing(db, row_count, database_url,
                                                       fake_scraper):
    """A loader that raises yields a non-200 response and leaves no rows."""
    def exploding_loader(records):
        raise RuntimeError("disk full")

    app = create_app({"TESTING": True}, scraper=fake_scraper, loader=exploding_loader,
                     run_async=False, database_url=database_url)
    response = app.test_client().post("/pull-data")

    assert response.status_code == 500
    assert response.get_json()["ok"] is False
    assert row_count() == 0
    # The busy flag is released so the app is not wedged after a failure.
    assert get_services(app).state.running is False
    assert get_services(app).state.last_error == "disk full"


def test_scraper_failure_returns_500(db, database_url):
    """A scraper that raises is reported rather than crashing the request."""
    def exploding_scraper(known):
        raise RuntimeError("Cloudflare challenge")

    app = create_app({"TESTING": True}, scraper=exploding_scraper,
                     loader=lambda records: (0, 0, 0), run_async=False,
                     database_url=database_url)
    response = app.test_client().post("/pull-data")

    assert response.status_code == 500
    assert "Cloudflare challenge" in response.get_json()["error"]


def test_update_analysis_failure_returns_500():
    """A failing analysis provider makes the update endpoint report an error."""
    def exploding_analysis():
        raise RuntimeError("query timeout")

    app = create_app({"TESTING": True}, analysis=exploding_analysis, run_async=False)
    response = app.test_client().post("/update-analysis")

    assert response.status_code == 500
    assert response.get_json()["ok"] is False
    assert "query timeout" in response.get_json()["error"]
