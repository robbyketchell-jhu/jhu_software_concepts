"""
Module 2:

As mentioned in the assignment doc, Cloudflare blocks direct requests (HTTP 403), so I applied the recommendation
of approving the captcha myself (once), and then keeping that page open and active in my browser.
the HTML comes from a Chrome, urllib3 builds
and validates URLs, BeautifulSoup parses the HTML, and the script drives the
Chrome tab from page to page.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.robotparser
import urllib3
from bs4 import BeautifulSoup

BASE_URL = "https://www.thegradcafe.com" # This is the base url for the website we are scraping
START_PATH = "/survey" # this is the path to the first set of data (before the cursor is needed)
OUT_FILE = "applicant_data.json" # for storing the scraped json
STATE_FILE = "scrape_state.json"

TARGET_RECORDS = 30000 # the minimum for the module
PAGE_PAUSE = 1.0 # courtesy pause between pages - trying to be polite :)
LOAD_TIMEOUT = 45.0 # max wait for one page to render - only time I saw this timeout was when I forgot to keep the page active in the Chrome browser
POLL_INTERVAL = 0.4 # time betrween polling for Chrome to finish loading results

DECISIONS = ("Accepted", "Rejected", "Interview", "Wait listed") 
SEMESTER_REGEX = re.compile(r"^(Fall|Spring|Summer|Winter)\s+\d{4}$")
STUDENT_TYPES = ("American", "International", "Other")


def build_url(path=START_PATH, cursor=None):
    """Build and validate a GradCafe URL with urllib3 ."""
    parsed = urllib3.util.parse_url(BASE_URL + path)
    if parsed.host != "www.thegradcafe.com":
        raise ValueError(f"refusing to build URL for {parsed.host}")
    url = str(parsed)
    return f"{url}?cursor={cursor}" if cursor else url # On the first pass, we don't need the cursor


def fetch_robots_txt():
    """Fetch robots.txt with urllib3. Returns (status_code, text)."""
    http = urllib3.PoolManager(timeout=urllib3.Timeout(connect=10, read=10))
    response = http.request("GET", f"{BASE_URL}/robots.txt")
    return response.status, response.data.decode("utf-8", errors="replace")


def check_robots(path=START_PATH, user_agent="*"):
    """Confirm robots.txt permits the path before scraping (SHALL requirement).

    Returns (allowed, crawl_delay). Raises if robots.txt can't be read at all,
    rather than silently assuming either answer.
    """
    try:
        status, text = fetch_robots_txt()
    except Exception as exc:
        raise RuntimeError(
            f"Could not fetch {BASE_URL}/robots.txt ({exc}).\n"
            "Open it in your browser, confirm /survey is allowed, save the\n"
            "screenshot, then re-run with --robots-verified."
        ) from exc

    if status != 200:
        raise RuntimeError(
            f"robots.txt returned HTTP {status}.\n"
            "Open it in your browser, confirm /survey is allowed, save the\n"
            "screenshot, then re-run with --robots-verified."
        )

    parser = urllib.robotparser.RobotFileParser()
    parser.parse(text.splitlines())

    url = build_url(path)
    allowed = parser.can_fetch(user_agent, url)
    delay = parser.crawl_delay(user_agent)

    print(f"robots.txt (HTTP {status}): {url} -> "
          f"{'ALLOWED' if allowed else 'DISALLOWED'}"
          f"{f', crawl-delay {delay}s' if delay else ''}")
    return allowed, delay


def run_js(js):
    """Run JavaScript in Chrome's frontmost tab, return the result."""
    script = f'''
tell application "Google Chrome"
  tell active tab of front window
    execute javascript "{js}"
  end tell
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"osascript failed: {result.stderr.strip()}")
    return result.stdout


def get_html():
    return run_js("document.documentElement.outerHTML")


def navigate(url):
    script = f'''
tell application "Google Chrome"
  set URL of active tab of front window to "{url}"
end tell
'''
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"navigation failed: {result.stderr.strip()}")


def wait_for_results():
    """Block until the tab shows a rendered results page."""
    deadline = time.time() + LOAD_TIMEOUT
    while time.time() < deadline:
        if run_js("document.readyState").strip() == "complete":
            title = run_js("document.title")
            if "Just a moment" in title or "Attention Required" in title:
                raise RuntimeError(
                    "Cloudflare is challenging the tab again.\n"
                    "Clear it in Chrome, then re-run with --resume."
                )
            count = run_js(
                "String(Array.from(document.getElementsByTagName('a'))"
                ".filter(function(a){return a.href.indexOf('/result/')>-1;})"
                ".length)"
            ).strip()
            if count.isdigit() and int(count) > 0:
                return
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"page did not render within {LOAD_TIMEOUT}s")


def _parse_decision(text):
    """'Accepted on Sep 11' -> ('Accepted', 'Sep 11')"""
    for decision in DECISIONS:
        if text.startswith(decision):
            rest = text[len(decision):].strip()
            date = rest[3:].strip() if rest.startswith("on ") else None
            return decision, date
    return None, None


def _parse_tags(tag_row, record):
    """Read the badge row: season, student type, GRE scores, GPA."""
    for badge in tag_row.select("div div"):
        text = badge.get_text(" ", strip=True)
        if SEMESTER_REGEX.match(text):
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


def _parse_entry_page(html):
    """Pull every applicant record out of one results page."""
    soup = BeautifulSoup(html, "html.parser")
    records = []

    for link in soup.find_all("a", href=lambda h: h and "/result/" in h):
        row = link.find_parent("tr")
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
            # Raw source text, kept verbatim for traceability (SHALL).
            "raw_main_row": row.get_text(" | ", strip=True),
            "raw_tag_row": None,
            "raw_comment_row": None,
        }

        spans = cells[1].find_all("span")
        if spans:
            record["program"] = spans[0].get_text(" ", strip=True)
            if len(spans) > 1:
                record["degree"] = spans[-1].get_text(" ", strip=True)

        decision, date = _parse_decision(cells[3].get_text(" ", strip=True))
        record["status"] = decision
        if decision == "Accepted":
            record["accept_date"] = date
        elif decision == "Rejected":
            record["reject_date"] = date

        tag_row = row.find_next_sibling("tr")
        if tag_row and not tag_row.find("a", href=lambda h: h and "/result/" in h):
            record["raw_tag_row"] = tag_row.get_text(" | ", strip=True)
            _parse_tags(tag_row, record)

            comment_row = tag_row.find_next_sibling("tr")
            if comment_row and comment_row.find("p"):
                paragraph = comment_row.find("p")
                record["raw_comment_row"] = paragraph.get_text(" ", strip=True)
                record["comments"] = paragraph.get_text(" ", strip=True)

        records.append(record)

    return records


def scrape_data(html):
    """Pull applicant records out of one results page (public entry point)."""
    return _parse_entry_page(html)


def _find_next_url(html):
    """The 'Next' link's href, or None on the last page.

    Matched by get_text() rather than string= — the <a> contains an inline
    SVG arrow, so string= never matches.
    """
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        if "Next" in a.get_text() and "cursor=" in a["href"]:
            href = a["href"]
            return BASE_URL + href if href.startswith("/") else href
    return None


def save_data(records, filename=OUT_FILE):
    """Write atomically so a crash can't truncate the file."""
    tmp = filename + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    os.replace(tmp, filename)


def load_data(filename=OUT_FILE):
    if os.path.exists(filename) and os.path.getsize(filename):
        with open(filename, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_state(next_url, pages_done):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"next_url": next_url, "pages_done": pages_done}, f)


def load_state():
    if os.path.exists(STATE_FILE) and os.path.getsize(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def run(target, max_pages, resume, robots_verified=False):
    if robots_verified:
        print("robots.txt: manually verified by user (--robots-verified)")
        crawl_delay = None
    else:
        allowed, crawl_delay = check_robots()
        if not allowed:
            raise RuntimeError("robots.txt disallows /survey — not scraping.")
    pause = max(PAGE_PAUSE, crawl_delay or 0)

    records = load_data() if resume else []
    seen = {r["url"] for r in records}
    state = load_state() if resume else {}
    pages_done = state.get("pages_done", 0)
    next_url = state.get("next_url")

    if resume and next_url:
        print(f"Resuming: {len(records)} records, {pages_done} pages done")
        navigate(next_url)
        wait_for_results()
    else:
        wait_for_results()   # use whatever page is already open

    start = time.time()
    added = 0

    while True:
        if len(records) >= target:
            print(f"\nReached target of {target} records.")
            break
        if max_pages and pages_done >= max_pages:
            print(f"\nReached page limit of {max_pages}.")
            break

        html = get_html()
        page_records = _parse_entry_page(html)
        if not page_records:
            print("\nNo records on this page — stopping.")
            break

        fresh = [r for r in page_records if r["url"] not in seen]
        for r in fresh:
            seen.add(r["url"])
        records.extend(fresh)
        added += len(fresh)
        pages_done += 1

        next_url = _find_next_url(html)

        save_data(records)
        save_state(next_url, pages_done)

        elapsed = time.time() - start
        rate = added / elapsed * 60 if elapsed else 0
        remaining = (target - len(records)) / rate if rate else 0
        print(
            f"page {pages_done}: +{len(fresh)} | {len(records)}/{target} "
            f"| {elapsed/60:.1f} min | ~{remaining:.0f} min left"
        )

        if not next_url:
            print("\nNo Next link — reached the end of the results.")
            break

        time.sleep(pause)
        navigate(next_url)
        wait_for_results()

    elapsed = time.time() - start
    print(f"\n{added} new records this run ({len(records)} total)")
    print(f"{pages_done} pages, {elapsed/60:.1f} minutes")
    print(f"Saved to {OUT_FILE}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=int, default=TARGET_RECORDS,
                        help=f"stop at this many records (default {TARGET_RECORDS})")
    parser.add_argument("--pages", type=int, default=None,
                        help="stop after this many pages (for testing)")
    parser.add_argument("--resume", action="store_true",
                        help="continue from scrape_state.json")
    parser.add_argument("--robots-verified", action="store_true",
                        help="you checked robots.txt in the browser yourself "
                             "(use only when the automated fetch is blocked)")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("This drives Chrome via AppleScript; macOS only.", file=sys.stderr)
        return 1

    print("Start URL:", build_url())
    try:
        run(args.target, args.pages, args.resume, args.robots_verified)
    except KeyboardInterrupt:
        print("\n\nStopped. Progress saved — re-run with --resume.")
        return 0
    except RuntimeError as e:
        print(f"\nStopped: {e}", file=sys.stderr)
        print("Progress saved — re-run with --resume.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())