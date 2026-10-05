"""Grad Cafe scraper.

The module keeps three concerns apart so that each can be tested on its own:

* **URLs and robots** - built and validated with ``urllib3``.
* **Parsing** - pure functions over HTML text, using BeautifulSoup.
* **Paging** - :func:`scrape_pages` walks the result pages using an injected
  browser object, so tests pass a fake and nothing ever reaches the network.

Live use still needs the Module 2 setup: allow JavaScript from Apple Events
in Chrome, open the survey page and clear the Cloudflare check, then leave
that window frontmost.
"""

import json
import os
import re
import time
import urllib.robotparser

import urllib3
from bs4 import BeautifulSoup

from .browser import BrowserError, ChromeBrowser

#: Root of the site being scraped.
BASE_URL = "https://www.thegradcafe.com"
#: Path of the results listing.
START_PATH = "/survey"
#: Courtesy pause between pages, in seconds.
PAGE_PAUSE = 1.0
#: Maximum seconds to wait for one page to render.
LOAD_TIMEOUT = 45.0
#: How often to open a fresh tab, in pages.
RECYCLE_EVERY = 100
#: Seconds between render checks.
POLL_INTERVAL = 0.4

#: Decision words Grad Cafe uses in the status cell.
DECISIONS = ("Accepted", "Rejected", "Interview", "Wait listed")
#: Student type badges.
STUDENT_TYPES = ("American", "International", "Other")

#: Matches a term badge such as ``"Fall 2026"``.
SEASON_RE = re.compile(r"^(Fall|Spring|Summer|Winter)\s+\d{4}$")


class ScrapeError(RuntimeError):
    """Raised when scraping cannot continue."""


def build_url(path=START_PATH, cursor=None):
    """Build and validate a Grad Cafe URL.

    :param path: path below :data:`BASE_URL`.
    :param cursor: optional paging cursor.
    :returns: the absolute URL.
    :raises ValueError: when the URL would point at another host.
    """
    parsed = urllib3.util.parse_url(BASE_URL + path)
    if parsed.host != "www.thegradcafe.com":
        raise ValueError(f"refusing to build URL for {parsed.host}")
    url = str(parsed)
    return f"{url}?cursor={cursor}" if cursor else url


def fetch_robots_txt(http=None):
    """Fetch ``robots.txt``.

    :param http: a ``urllib3`` pool manager; injected by tests.
    :returns: a ``(status_code, text)`` tuple.
    """
    http = http or urllib3.PoolManager(timeout=urllib3.Timeout(connect=10, read=10))
    response = http.request("GET", f"{BASE_URL}/robots.txt")
    return response.status, response.data.decode("utf-8", errors="replace")


def check_robots(path=START_PATH, user_agent="*", http=None):
    """Confirm ``robots.txt`` permits *path* before scraping.

    :param path: the path to check.
    :param user_agent: user agent to check the rules for.
    :param http: a ``urllib3`` pool manager; injected by tests.
    :returns: an ``(allowed, crawl_delay)`` tuple.
    :raises ScrapeError: when ``robots.txt`` cannot be read.
    """
    try:
        status, text = fetch_robots_txt(http)
    except Exception as exc:
        raise ScrapeError(f"Could not fetch {BASE_URL}/robots.txt ({exc}).") from exc

    if status != 200:
        raise ScrapeError(f"robots.txt returned HTTP {status}.")

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    url = build_url(path)
    return parser.can_fetch(user_agent, url), parser.crawl_delay(user_agent)


def parse_decision(text):
    """Split a status cell into its decision and date.

    ``"Accepted on Sep 11"`` becomes ``("Accepted", "Sep 11")``.

    :param text: the cell text.
    :returns: a ``(decision, date)`` tuple, both ``None`` when unrecognised.
    """
    for decision in DECISIONS:
        if text.startswith(decision):
            rest = text[len(decision):].strip()
            date = rest[3:].strip() if rest.startswith("on ") else None
            return decision, date
    return None, None


def parse_tags(tag_row, record):
    """Read the badge row into *record*: term, student type, GRE scores, GPA.

    :param tag_row: the ``<tr>`` holding the badges.
    :param record: the record dict to update in place.
    """
    for badge in tag_row.select("div div"):
        text = badge.get_text(" ", strip=True)
        if SEASON_RE.match(text):
            record["semester_start"] = text
        elif text in STUDENT_TYPES:
            record["student_type"] = text
        elif text.startswith("GRE AW"):
            record["gre_aw"] = text[6:].strip()
        elif text.startswith("GRE V"):
            record["gre_v"] = text[5:].strip()
        elif text.startswith("GRE"):
            record["gre"] = text[3:].strip()
        elif text.startswith("GPA"):
            record["gpa"] = text[3:].strip()


def scrape_data(html):
    """Pull every applicant record out of one results page.

    :param html: the page HTML (or the table fragment the browser returns).
    :returns: a list of raw record dicts.
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []

    for link in soup.find_all("a", href=lambda h: h and "/result/" in h):
        row = link.find_parent("tr")
        if row is None:
            continue
        cells = row.find_all("td")
        if len(cells) < 5:
            continue

        href = link["href"]
        record = {
            "university": cells[0].get_text(" ", strip=True),
            "program": None,
            "degree": None,
            "date_added": cells[2].get_text(" ", strip=True),
            "url": BASE_URL + href if href.startswith("/") else href,
            "status": None,
            "accept_date": None,
            "reject_date": None,
            "semester_start": None,
            "student_type": None,
            "gre": None,
            "gre_v": None,
            "gre_aw": None,
            "gpa": None,
            "comments": None,
            # Raw source text, kept verbatim for traceability.
            "raw_main_row": row.get_text(" | ", strip=True),
            "raw_tag_row": None,
            "raw_comment_row": None,
        }

        spans = cells[1].find_all("span")
        if spans:
            record["program"] = spans[0].get_text(" ", strip=True)
            if len(spans) > 1:
                record["degree"] = spans[-1].get_text(" ", strip=True)

        decision, date = parse_decision(cells[3].get_text(" ", strip=True))
        record["status"] = decision
        if decision == "Accepted":
            record["accept_date"] = date
        elif decision == "Rejected":
            record["reject_date"] = date

        tag_row = row.find_next_sibling("tr")
        if tag_row and not tag_row.find("a", href=lambda h: h and "/result/" in h):
            record["raw_tag_row"] = tag_row.get_text(" | ", strip=True)
            parse_tags(tag_row, record)

            comment_row = tag_row.find_next_sibling("tr")
            if comment_row and comment_row.find("p"):
                paragraph = comment_row.find("p")
                record["raw_comment_row"] = paragraph.get_text(" ", strip=True)
                record["comments"] = paragraph.get_text(" ", strip=True)

        records.append(record)

    return records


def find_next_url(html):
    """Return the "Next" link's URL, or ``None`` on the last page.

    Matched on link text rather than an exact string because the anchor
    contains an inline SVG arrow.

    :param html: the page HTML.
    :returns: the absolute URL of the next page, or ``None``.
    """
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.find_all("a", href=True):
        if "Next" in anchor.get_text() and "cursor=" in anchor["href"]:
            href = anchor["href"]
            return BASE_URL + href if href.startswith("/") else href
    return None


def wait_for_results(browser, previous_id=None, timeout=LOAD_TIMEOUT,
                     poll=POLL_INTERVAL, clock=None, sleeper=None):
    """Block until the tab shows a freshly rendered results page.

    Grad Cafe is a single page app, so after navigating the previous page's
    rows are often still in the DOM. When the caller knows what the previous
    page started with, this waits for that first id to change.

    :param browser: an object exposing ``title()`` and ``first_result_id()``.
    :param previous_id: the first result id of the page being replaced.
    :param timeout: seconds to wait before giving up.
    :param poll: seconds between checks.
    :param clock: callable returning the current time; injected by tests.
    :param sleeper: callable used to wait; injected by tests.
    :returns: the first result id now on the page.
    :raises ScrapeError: on a Cloudflare challenge or a render timeout.
    """
    clock = clock or time.monotonic
    sleeper = sleeper or time.sleep
    deadline = clock() + timeout
    while clock() < deadline:
        title = browser.title()
        if "Just a moment" in title or "Attention Required" in title:
            raise ScrapeError(
                "Cloudflare is challenging the tab again. Clear it in Chrome and retry."
            )
        current = browser.first_result_id()
        if current and (previous_id is None or current != previous_id):
            return current
        sleeper(poll)
    raise ScrapeError(f"page did not render within {timeout}s")


def save_data(records, filename):
    """Write *records* to *filename* atomically.

    A crash mid-write cannot truncate the real file because the data lands in
    a temporary file that is then renamed.

    :param records: the records to serialise.
    :param filename: destination path.
    """
    tmp = filename + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(records, handle, indent=2, ensure_ascii=False)
    os.replace(tmp, filename)


def load_saved(filename):
    """Read records previously written by :func:`save_data`.

    :param filename: path to read.
    :returns: the records, or ``[]`` when the file is missing or empty.
    """
    if os.path.exists(filename) and os.path.getsize(filename):
        with open(filename, encoding="utf-8") as handle:
            return json.load(handle)
    return []


def scrape_pages(browser=None, max_pages=25, known_urls=None, stop_when_seen=True,
                 pause=PAGE_PAUSE, sleeper=None, log=None):
    """Walk the results pages newest first and return the records found.

    :param browser: object implementing the browser interface described in
        :mod:`src.browser`. Defaults to a real :class:`~src.browser.ChromeBrowser`.
    :param max_pages: stop after this many pages.
    :param known_urls: result URLs already stored; matching records are not
        returned. The set is updated in place with the new URLs.
    :param stop_when_seen: stop as soon as a page yields nothing new, which is
        what makes an incremental pull cheap.
    :param pause: courtesy delay between pages.
    :param sleeper: callable used to wait; injected by tests.
    :param log: callable receiving progress messages.
    :returns: the list of new raw records.
    :raises ScrapeError: when the first page never renders.
    """
    browser = browser or ChromeBrowser()
    sleeper = sleeper or time.sleep
    log = log or (lambda message: None)
    known = set() if known_urls is None else known_urls

    new_records = []
    start_url = build_url()
    browser.ensure_window(start_url)
    browser.navigate(start_url)
    last_first_id = wait_for_results(browser, sleeper=sleeper)

    for page in range(1, max_pages + 1):
        html = browser.current_html()
        page_records = scrape_data(html)
        if not page_records:
            # Usually a render gap rather than the end of the results.
            sleeper(2)
            html = browser.current_html()
            page_records = scrape_data(html)
        if not page_records:
            log(f"page {page}: no records found, stopping")
            break

        fresh = [r for r in page_records if r["url"] not in known]
        known.update(r["url"] for r in fresh)
        new_records.extend(fresh)
        log(
            f"page {page}: {len(fresh)} new of {len(page_records)} entries "
            f"({len(new_records)} new so far)"
        )

        if stop_when_seen and not fresh:
            log("Reached entries that are already in the database.")
            break

        next_url = find_next_url(html)
        if not next_url:
            log("No Next link, reached the end of the results.")
            break

        if page % RECYCLE_EVERY == 0:
            try:
                browser.recycle_tab(next_url)
            except BrowserError as exc:  # fall back to plain navigation
                log(f"tab recycle failed ({exc}), navigating instead")
                browser.navigate(next_url)
        else:
            sleeper(pause)
            browser.navigate(next_url)
        last_first_id = wait_for_results(browser, last_first_id, sleeper=sleeper)

    return new_records
