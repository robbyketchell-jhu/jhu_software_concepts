"""Scraper parsing, paging and the Chrome driver.

Nothing here touches the network or launches Chrome: the browser is a fake
implementing the small interface described in :mod:`src.browser`, and the
``osascript`` runner is a stub.
"""

import json
import subprocess

import pytest

from src import scrape
from src.browser import APPLE_EVENT_TIMEOUT, BrowserError, ChromeBrowser

pytestmark = pytest.mark.db


# ----------------------------------------------------------------- fixtures
RESULTS_HTML = """
<table><tbody>
  <tr>
    <td>Johns Hopkins University</td>
    <td><span>Computer Science</span><span>Masters</span></td>
    <td>Sep 12, 2026</td>
    <td>Accepted on Sep 11</td>
    <td><a href="/result/1000001">See More</a></td>
  </tr>
  <tr><td><div>
    <div>Fall 2026</div><div>American</div>
    <div>GPA 3.90</div><div>GRE 168</div><div>GRE V 161</div><div>GRE AW 4.5</div>
    <div>Total comments</div>
  </div></td></tr>
  <tr><td><p>Over the moon about this one.</p></td></tr>

  <tr>
    <td>Stanford University</td>
    <td><span>Physics</span></td>
    <td>Sep 11, 2026</td>
    <td>Rejected on Sep 10</td>
    <td><a href="https://www.thegradcafe.com/result/1000002">See More</a></td>
  </tr>
  <tr><td><div><div>Spring 2027</div><div>International</div></div></td></tr>

  <tr>
    <td>Yale University</td>
    <td><span>History</span><span>PhD</span></td>
    <td>Sep 10, 2026</td>
    <td>Wait listed on Sep 09</td>
    <td><a href="/result/1000003">See More</a></td>
  </tr>

  <tr>
    <td>Duke University</td>
    <td>Statistics</td>
    <td>Sep 09, 2026</td>
    <td>Interview</td>
    <td><a href="/result/1000004">See More</a></td>
  </tr>

  <tr><td>too</td><td>few</td><td><a href="/result/1000005">cells</a></td></tr>
</tbody></table>
<a href="/result/1000006">orphan link outside any row</a>
<a href="/survey?cursor=NEXTCURSOR">Next</a>
"""

NO_NEXT_HTML = RESULTS_HTML.replace('<a href="/survey?cursor=NEXTCURSOR">Next</a>', "")


class FakeBrowser:
    """Minimal stand-in for :class:`src.browser.ChromeBrowser`.

    :param pages: HTML returned by successive ``current_html`` calls.
    :param titles: titles returned by successive ``title`` calls.
    :param ids: first-result ids returned by successive calls.
    :param recycle_error: exception raised by ``recycle_tab``.
    """

    def __init__(self, pages=None, titles=None, ids=None, recycle_error=None):
        self.pages = list(pages or [RESULTS_HTML])
        self.titles = list(titles or [])
        self.ids = list(ids or [])
        self.recycle_error = recycle_error
        self.navigated = []
        self.recycled = []
        self.ensured = []
        self._page_index = 0
        self._id_counter = 0

    def current_html(self):
        page = self.pages[min(self._page_index, len(self.pages) - 1)]
        self._page_index += 1
        return page

    def title(self):
        return self.titles.pop(0) if self.titles else "Results"

    def first_result_id(self):
        if self.ids:
            return self.ids.pop(0)
        self._id_counter += 1
        return str(self._id_counter)

    def navigate(self, url):
        self.navigated.append(url)

    def recycle_tab(self, url):
        if self.recycle_error is not None:
            raise self.recycle_error
        self.recycled.append(url)

    def ensure_window(self, url):
        self.ensured.append(url)


# --------------------------------------------------------------------- URLs
def test_build_url_defaults_to_the_survey_page():
    """The default URL is the survey listing."""
    assert scrape.build_url() == "https://www.thegradcafe.com/survey"


def test_build_url_appends_a_cursor():
    """A paging cursor is appended as a query parameter."""
    assert scrape.build_url(cursor="abc").endswith("/survey?cursor=abc")


def test_build_url_refuses_another_host(monkeypatch):
    """The builder will not produce a URL for a different host."""
    monkeypatch.setattr(scrape, "BASE_URL", "https://example.com")
    with pytest.raises(ValueError, match="refusing to build URL"):
        scrape.build_url()


# ------------------------------------------------------------------ robots
class FakeResponse:
    """Stand-in for a ``urllib3`` response."""

    def __init__(self, status, text):
        self.status = status
        self.data = text.encode("utf-8")


class FakeHttp:
    """Stand-in for a ``urllib3`` pool manager."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def request(self, method, url):
        if self.error is not None:
            raise self.error
        return self.response


def test_fetch_robots_txt_returns_status_and_text():
    """The fetcher hands back the status code and the decoded body."""
    http = FakeHttp(FakeResponse(200, "User-agent: *\nAllow: /"))
    assert scrape.fetch_robots_txt(http) == (200, "User-agent: *\nAllow: /")


def test_check_robots_allows_the_survey_path():
    """A permissive robots.txt allows scraping and reports no crawl delay."""
    http = FakeHttp(FakeResponse(200, "User-agent: *\nAllow: /\n"))
    allowed, delay = scrape.check_robots(http=http)
    assert allowed is True
    assert delay is None


def test_check_robots_reports_a_disallow_and_crawl_delay():
    """A restrictive robots.txt is honoured, delay included."""
    body = "User-agent: *\nDisallow: /survey\nCrawl-delay: 5\n"
    allowed, delay = scrape.check_robots(http=FakeHttp(FakeResponse(200, body)))
    assert allowed is False
    assert delay == 5


def test_check_robots_raises_on_a_bad_status():
    """A non-200 robots.txt stops the scrape rather than guessing."""
    with pytest.raises(scrape.ScrapeError, match="HTTP 503"):
        scrape.check_robots(http=FakeHttp(FakeResponse(503, "")))


def test_check_robots_raises_when_the_fetch_fails():
    """A network error stops the scrape rather than guessing."""
    with pytest.raises(scrape.ScrapeError, match="Could not fetch"):
        scrape.check_robots(http=FakeHttp(error=OSError("no route to host")))


# ----------------------------------------------------------------- parsing
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Accepted on Sep 11", ("Accepted", "Sep 11")),
        ("Rejected on Sep 10", ("Rejected", "Sep 10")),
        ("Interview", ("Interview", None)),
        ("Wait listed on Sep 09", ("Wait listed", "Sep 09")),
        ("Total comments", (None, None)),
    ],
)
def test_parse_decision(text, expected):
    """The status cell splits into a decision and an optional date."""
    assert scrape.parse_decision(text) == expected


def test_scrape_data_extracts_every_well_formed_row():
    """Rows with the full five cells become records; malformed ones are skipped."""
    records = scrape.scrape_data(RESULTS_HTML)
    assert [r["url"].rsplit("/", 1)[-1] for r in records] == [
        "1000001", "1000002", "1000003", "1000004"
    ]


def test_scrape_data_reads_the_badge_row():
    """Term, student type, GPA and all three GRE scores come off the badges."""
    first = scrape.scrape_data(RESULTS_HTML)[0]
    assert first["semester_start"] == "Fall 2026"
    assert first["student_type"] == "American"
    assert first["gpa"] == "3.90"
    assert first["gre"] == "168"
    assert first["gre_v"] == "161"
    assert first["gre_aw"] == "4.5"


def test_scrape_data_reads_program_degree_status_and_comments():
    """The main row yields university, program, degree, status and comments."""
    first = scrape.scrape_data(RESULTS_HTML)[0]
    assert first["university"] == "Johns Hopkins University"
    assert first["program"] == "Computer Science"
    assert first["degree"] == "Masters"
    assert first["status"] == "Accepted"
    assert first["accept_date"] == "Sep 11"
    assert first["comments"] == "Over the moon about this one."


def test_scrape_data_handles_a_single_span_and_a_rejection():
    """A row with one span has no degree, and a rejection records its date."""
    second = scrape.scrape_data(RESULTS_HTML)[1]
    assert second["program"] == "Physics"
    assert second["degree"] is None
    assert second["status"] == "Rejected"
    assert second["reject_date"] == "Sep 10"
    assert second["comments"] is None
    assert second["url"] == "https://www.thegradcafe.com/result/1000002"


def test_scrape_data_handles_a_row_with_no_badge_row():
    """A row whose sibling is another result row keeps its badge fields empty."""
    third = scrape.scrape_data(RESULTS_HTML)[2]
    assert third["status"] == "Wait listed"
    assert third["semester_start"] is None
    assert third["student_type"] is None


def test_scrape_data_handles_a_cell_with_no_span():
    """A program cell holding bare text leaves program and degree unset."""
    fourth = scrape.scrape_data(RESULTS_HTML)[3]
    assert fourth["university"] == "Duke University"
    assert fourth["program"] is None
    assert fourth["degree"] is None
    assert fourth["status"] == "Interview"


def test_scrape_data_ignores_an_unrecognised_badge():
    """A badge matching none of the known patterns is skipped."""
    first = scrape.scrape_data(RESULTS_HTML)[0]
    assert first["semester_start"] == "Fall 2026"
    assert first["gpa"] == "3.90"


def test_scrape_data_on_an_empty_page_returns_nothing():
    """A page with no result links yields no records."""
    assert scrape.scrape_data("<html><body>nothing here</body></html>") == []


def test_find_next_url_returns_the_absolute_next_link():
    """The Next anchor is resolved against the site root."""
    assert scrape.find_next_url(RESULTS_HTML) == (
        "https://www.thegradcafe.com/survey?cursor=NEXTCURSOR"
    )


def test_find_next_url_handles_an_absolute_href():
    """An already-absolute Next link is returned unchanged."""
    html = '<a href="https://www.thegradcafe.com/survey?cursor=Z">Next</a>'
    assert scrape.find_next_url(html).endswith("cursor=Z")


def test_find_next_url_returns_none_on_the_last_page():
    """No Next anchor means the end of the results."""
    assert scrape.find_next_url(NO_NEXT_HTML) is None


# ----------------------------------------------------------- wait_for_results
def test_wait_for_results_returns_the_first_id():
    """A rendered page yields the id of its first result."""
    browser = FakeBrowser(ids=["4242"])
    assert scrape.wait_for_results(browser, sleeper=lambda _: None) == "4242"


def test_wait_for_results_waits_for_the_id_to_change():
    """When the previous id is known, the stale page is skipped."""
    browser = FakeBrowser(ids=["old", "old", "new"])
    result = scrape.wait_for_results(browser, previous_id="old", sleeper=lambda _: None)
    assert result == "new"


def test_wait_for_results_skips_an_empty_id():
    """A page that has not rendered any results yet is waited out."""
    browser = FakeBrowser(ids=["", "ready"])
    assert scrape.wait_for_results(browser, sleeper=lambda _: None) == "ready"


def test_wait_for_results_detects_a_cloudflare_challenge():
    """A challenge page is reported rather than silently retried forever."""
    browser = FakeBrowser(titles=["Just a moment..."])
    with pytest.raises(scrape.ScrapeError, match="Cloudflare"):
        scrape.wait_for_results(browser, sleeper=lambda _: None)


def test_wait_for_results_times_out():
    """A page that never renders raises instead of hanging."""
    ticks = iter([0.0, 1.0, 99.0])
    browser = FakeBrowser(ids=["", "", ""])
    with pytest.raises(scrape.ScrapeError, match="did not render"):
        scrape.wait_for_results(
            browser, timeout=10, clock=lambda: next(ticks), sleeper=lambda _: None
        )


# -------------------------------------------------------------- persistence
def test_save_and_load_round_trip(tmp_path):
    """Saved records read back identically."""
    path = str(tmp_path / "records.json")
    scrape.save_data([{"url": "a"}], path)
    assert scrape.load_saved(path) == [{"url": "a"}]


def test_save_data_writes_atomically(tmp_path):
    """The temporary file is renamed away, leaving only the real file."""
    path = str(tmp_path / "records.json")
    scrape.save_data([{"url": "a"}], path)
    assert not (tmp_path / "records.json.tmp").exists()
    assert json.loads((tmp_path / "records.json").read_text()) == [{"url": "a"}]


def test_load_saved_returns_empty_for_a_missing_file(tmp_path):
    """A path that does not exist reads as no records."""
    assert scrape.load_saved(str(tmp_path / "absent.json")) == []


def test_load_saved_returns_empty_for_an_empty_file(tmp_path):
    """A zero-byte file reads as no records rather than raising."""
    path = tmp_path / "empty.json"
    path.write_text("")
    assert scrape.load_saved(str(path)) == []


# -------------------------------------------------------------- scrape_pages
def test_scrape_pages_returns_records_and_stops_at_the_last_page():
    """One page with no Next link yields its records and stops."""
    browser = FakeBrowser(pages=[NO_NEXT_HTML])
    messages = []

    records = scrape.scrape_pages(
        browser=browser, sleeper=lambda _: None, log=messages.append
    )

    assert len(records) == 4
    assert browser.ensured == ["https://www.thegradcafe.com/survey"]
    assert any("No Next link" in m for m in messages)


def test_scrape_pages_stops_when_everything_is_already_known():
    """An incremental pull stops at the first page with nothing new."""
    known = {f"https://www.thegradcafe.com/result/100000{n}" for n in (1, 2, 3, 4)}
    messages = []

    records = scrape.scrape_pages(
        browser=FakeBrowser(pages=[RESULTS_HTML]), known_urls=known,
        sleeper=lambda _: None, log=messages.append
    )

    assert records == []
    assert any("already in the database" in m for m in messages)


def test_scrape_pages_can_keep_going_past_known_rows():
    """``stop_when_seen=False`` keeps paging even with nothing new."""
    known = {f"https://www.thegradcafe.com/result/100000{n}" for n in (1, 2, 3, 4)}
    browser = FakeBrowser(pages=[RESULTS_HTML, NO_NEXT_HTML])

    records = scrape.scrape_pages(
        browser=browser, known_urls=known, stop_when_seen=False, max_pages=2,
        sleeper=lambda _: None
    )

    assert records == []
    assert browser.navigated  # it moved on to the second page


def test_scrape_pages_follows_the_next_link():
    """Paging continues while a Next link is present and pages are new."""
    second_page = RESULTS_HTML.replace("100000", "200000").replace(
        'cursor=NEXTCURSOR">Next', 'cursor=SECOND">Next'
    )
    browser = FakeBrowser(pages=[RESULTS_HTML, second_page])

    records = scrape.scrape_pages(browser=browser, max_pages=2, sleeper=lambda _: None)

    assert len(records) == 8
    # start page, then the Next link of page one, then the Next link of page two
    assert browser.navigated[0].endswith("/survey")
    assert browser.navigated[1].endswith("cursor=NEXTCURSOR")


def test_scrape_pages_retries_a_blank_page_once():
    """A render gap is re-read before being believed."""
    browser = FakeBrowser(pages=["<html></html>", NO_NEXT_HTML])
    records = scrape.scrape_pages(browser=browser, sleeper=lambda _: None)
    assert len(records) == 4


def test_scrape_pages_stops_after_two_blank_reads():
    """Two empty reads in a row end the run."""
    messages = []
    records = scrape.scrape_pages(
        browser=FakeBrowser(pages=["<html></html>"]), sleeper=lambda _: None,
        log=messages.append
    )
    assert records == []
    assert any("no records found" in m for m in messages)


def test_scrape_pages_recycles_the_tab_periodically(monkeypatch):
    """Every ``RECYCLE_EVERY`` pages a fresh tab is opened instead of navigating."""
    monkeypatch.setattr(scrape, "RECYCLE_EVERY", 1)
    second = RESULTS_HTML.replace("100000", "200000")
    browser = FakeBrowser(pages=[RESULTS_HTML, second])

    scrape.scrape_pages(browser=browser, max_pages=2, sleeper=lambda _: None)

    assert browser.recycled
    assert browser.navigated == ["https://www.thegradcafe.com/survey"]


def test_scrape_pages_falls_back_to_navigation_when_recycling_fails(monkeypatch):
    """A failed recycle never ends the run."""
    monkeypatch.setattr(scrape, "RECYCLE_EVERY", 1)
    second = RESULTS_HTML.replace("100000", "200000")
    browser = FakeBrowser(pages=[RESULTS_HTML, second],
                          recycle_error=BrowserError("tab gone"))
    messages = []

    records = scrape.scrape_pages(
        browser=browser, max_pages=2, sleeper=lambda _: None, log=messages.append
    )

    assert len(records) == 8
    assert any("recycle failed" in m for m in messages)


def test_scrape_pages_builds_a_real_browser_by_default(monkeypatch):
    """Omitting the browser constructs a :class:`ChromeBrowser`."""
    built = FakeBrowser(pages=[NO_NEXT_HTML])
    monkeypatch.setattr(scrape, "ChromeBrowser", lambda: built)
    monkeypatch.setattr(scrape.time, "sleep", lambda _: None)

    assert len(scrape.scrape_pages()) == 4
    assert built.ensured


# ------------------------------------------------------------------ browser
def completed(returncode=0, stdout="", stderr=""):
    """Build a :class:`subprocess.CompletedProcess` for the fake runner."""
    return subprocess.CompletedProcess(
        args=["osascript"], returncode=returncode, stdout=stdout, stderr=stderr
    )


class FakeRunner:
    """Records the AppleScript it was asked to run."""

    def __init__(self, results=None):
        self.results = list(results or [completed(stdout="ok")])
        self.scripts = []

    def __call__(self, args, capture_output=False, text=False):
        self.scripts.append(args[-1])
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


def browser_with(results=None):
    """Build a :class:`ChromeBrowser` wired to a fake runner."""
    runner = FakeRunner(results)
    return ChromeBrowser(runner=runner, sleeper=lambda _: None), runner


def test_browser_uses_the_configured_timeout():
    """The Apple Event timeout appears in the generated script."""
    browser, runner = browser_with()
    browser.run_js("document.title")
    assert f"with timeout of {APPLE_EVENT_TIMEOUT} seconds" in runner.scripts[0]


def test_run_js_returns_stdout():
    """A successful osascript call returns its stdout."""
    browser, _ = browser_with([completed(stdout="Grad Cafe")])
    assert browser.run_js("document.title") == "Grad Cafe"


def test_run_js_retries_then_succeeds():
    """A transient Apple Event failure is retried."""
    browser, runner = browser_with(
        [completed(1, stderr="-1712"), completed(stdout="second try")]
    )
    assert browser.run_js("x", attempts=2) == "second try"
    assert len(runner.scripts) == 2


def test_run_js_raises_after_the_last_attempt():
    """Repeated failures raise :class:`BrowserError`."""
    browser, _ = browser_with([completed(1, stderr="boom")])
    with pytest.raises(BrowserError, match="after 2 tries"):
        browser.run_js("x", attempts=2)


def test_title_and_html_and_first_result_id():
    """The convenience readers delegate to ``run_js``."""
    browser, _ = browser_with([completed(stdout="  4242\n")])
    assert browser.first_result_id() == "4242"

    browser, _ = browser_with([completed(stdout="<table></table>")])
    assert browser.current_html() == "<table></table>"

    browser, _ = browser_with([completed(stdout="Results")])
    assert browser.title() == "Results"


def test_navigate_sends_the_url():
    """Navigation puts the URL into the AppleScript."""
    browser, runner = browser_with()
    browser.navigate("https://example.test/page")
    assert "https://example.test/page" in runner.scripts[0]


def test_navigate_raises_when_chrome_refuses():
    """A non-zero exit becomes a :class:`BrowserError`."""
    browser, _ = browser_with([completed(1, stderr="no window")])
    with pytest.raises(BrowserError, match="navigation failed"):
        browser.navigate("https://example.test")


def test_recycle_tab_opens_a_new_tab():
    """Recycling asks Chrome for a new tab at the given URL."""
    browser, runner = browser_with()
    browser.recycle_tab("https://example.test/next")
    assert "make new tab" in runner.scripts[0]


def test_recycle_tab_raises_on_failure():
    """A failed recycle is reported so the caller can fall back."""
    browser, _ = browser_with([completed(1, stderr="-1719")])
    with pytest.raises(BrowserError, match="tab recycle failed"):
        browser.recycle_tab("https://example.test")


def test_ensure_window_never_raises():
    """Window recovery swallows failures because the caller retries anyway."""
    browser, runner = browser_with([completed(1, stderr="nope")])
    browser.ensure_window("https://example.test")
    assert "make new window" in runner.scripts[0]


def test_browser_defaults_to_subprocess_run():
    """Constructed without a runner, the driver uses :mod:`subprocess`."""
    assert ChromeBrowser()._run is subprocess.run
