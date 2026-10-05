"""
GradCafe scraper — Module 2.
 
Cloudflare blocks direct requests (HTTP 403), so the HTML comes from a Chrome
window where you've already cleared the human check yourself. urllib3 builds
and validates URLs, BeautifulSoup parses the HTML, and the script drives the
Chrome tab from page to page.
 
Usage:
    1. Chrome: View > Developer > Allow JavaScript from Apple Events
    2. Open https://www.thegradcafe.com/survey in Chrome, clear the check
    3. Leave that Chrome window frontmost, then:
 
        python scrape.py              # pull until TARGET_RECORDS
        python scrape.py --resume     # continue after a stop
        python scrape.py --pages 5    # short test run
 
Progress is saved after every page. Ctrl-C is safe — re-run with --resume.
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
 
BASE_URL = "https://www.thegradcafe.com"
START_PATH = "/survey"
OUT_FILE = "applicant_data.json"
STATE_FILE = "scrape_state.json"
 
TARGET_RECORDS = 30000
PAGE_PAUSE = 1.0        # courtesy pause between pages
LOAD_TIMEOUT = 45.0     # max wait for one page to render
APPLE_EVENT_TIMEOUT = 300  # seconds before AppleScript gives up on Chrome
RECYCLE_EVERY = 100     # open a fresh tab this often (frees Chrome memory)
POLL_INTERVAL = 0.4
 
DECISIONS = ("Accepted", "Rejected", "Interview", "Wait listed")
SEASON_RE = re.compile(r"^(Fall|Spring|Summer|Winter)\s+\d{4}$")
STUDENT_TYPES = ("American", "International", "Other")
 
 
# ---------------------------------------------------------------- URLs
def build_url(path=START_PATH, cursor=None):
    """Build and validate a GradCafe URL with urllib3."""
    parsed = urllib3.util.parse_url(BASE_URL + path)
    if parsed.host != "www.thegradcafe.com":
        raise ValueError(f"refusing to build URL for {parsed.host}")
    url = str(parsed)
    return f"{url}?cursor={cursor}" if cursor else url
 
 
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
 
 
# ---------------------------------------------------------------- Chrome
def run_js(js, attempts=3):
    """Run JavaScript in Chrome's frontmost tab, return the result.
 
    Wrapped in `with timeout` because AppleScript defaults to 60s and Chrome
    can exceed that when it's been running a long time. Transient AppleEvent
    failures are retried rather than killing a multi-hour run.
    """
    script = f'''
with timeout of {APPLE_EVENT_TIMEOUT} seconds
  tell application "Google Chrome"
    tell active tab of front window
      execute javascript "{js}"
    end tell
  end tell
end timeout
'''
    last_error = ""
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True
        )
        if result.returncode == 0:
            return result.stdout
        last_error = result.stderr.strip()
        if attempt < attempts:
            wait = 2 * attempt
            print(f"  (Chrome didn't answer, retry {attempt}/{attempts - 1} "
                  f"in {wait}s)")
            time.sleep(wait)
    raise RuntimeError(f"osascript failed after {attempts} tries: {last_error}")
 
 
def get_html():
    """Return just the results table plus the Next link.
 
    The full document is ~900KB and pushing that through an Apple Event is
    what causes -1712 timeouts. The table plus one anchor is ~60KB and
    contains everything the parser needs.
    """
    return run_js(
        "(function(){"
        "var t=document.querySelector('table');"
        "var n=Array.from(document.getElementsByTagName('a')).filter("
        "function(a){return a.href.indexOf('cursor=')>-1"
        " && a.textContent.indexOf('Next')>-1;});"
        "return (t?t.outerHTML:'')+(n.length?n[n.length-1].outerHTML:'');"
        "})()"
    )
 
 
def get_full_html():
    """The entire document — slower, only needed for debugging."""
    return run_js("document.documentElement.outerHTML")
 
 
def navigate(url):
    script = f'''
with timeout of {APPLE_EVENT_TIMEOUT} seconds
  tell application "Google Chrome"
    set URL of active tab of front window to "{url}"
  end tell
end timeout
'''
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"navigation failed: {result.stderr.strip()}")
 
 
def recycle_tab(url):
    """Open a fresh tab at `url`, then close the one tab it replaces.
 
    Navigating a single tab thousands of times leaks memory in the renderer —
    this SPA keeps history entries and detached DOM around — until Chrome
    stops answering Apple Events (-1712). A new tab starts clean and keeps the
    Cloudflare clearance cookie, so no re-verification is needed.
 
    Closes exactly one tab, by reference, captured before the new one is made.
    Never loops over tabs: closing the last tab in a window closes the window,
    and then every later call fails with -1719.
    """
    script = f'''
with timeout of {APPLE_EVENT_TIMEOUT} seconds
  tell application "Google Chrome"
    set theWindow to front window
    set oldTab to active tab of theWindow
    make new tab at end of tabs of theWindow with properties {{URL:"{url}"}}
    set active tab index of theWindow to (count of tabs of theWindow)
    try
      close oldTab
    end try
  end tell
end timeout
'''
    result = subprocess.run(
        ["osascript", "-e", script], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"tab recycle failed: {result.stderr.strip()}")
 
 
def ensure_window(url):
    """Reopen a Chrome window if there isn't one (recovers from -1719)."""
    script = f'''
with timeout of {APPLE_EVENT_TIMEOUT} seconds
  tell application "Google Chrome"
    if (count of windows) is 0 then
      make new window
      set URL of active tab of front window to "{url}"
    end if
    activate
  end tell
end timeout
'''
    subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
 
 
def first_result_id():
    """ID of the first /result/ link on the page, or '' if none yet."""
    return run_js(
        "(function(){"
        "var a=Array.from(document.getElementsByTagName('a')).filter("
        "function(x){return x.href.indexOf('/result/')>-1;});"
        "return a.length?a[0].href.split('/result/')[1]:'';"
        "})()"
    ).strip()
 
 
def wait_for_results(previous_id=None):
    """Block until the tab shows a rendered results page.
 
    This is a single-page app: after navigating, readyState is often already
    'complete' and the previous page's rows are still in the DOM. Waiting only
    for "some results exist" therefore captures the OLD page. So when we know
    what the previous page started with, we wait for that to change.
    """
    deadline = time.time() + LOAD_TIMEOUT
    while time.time() < deadline:
        title = run_js("document.title")
        if "Just a moment" in title or "Attention Required" in title:
            raise RuntimeError(
                "Cloudflare is challenging the tab again.\n"
                "Clear it in Chrome, then re-run with --resume."
            )
        current = first_result_id()
        if current and (previous_id is None or current != previous_id):
            return current
        time.sleep(POLL_INTERVAL)
    raise RuntimeError(f"page did not render within {LOAD_TIMEOUT}s")
 
 
# ---------------------------------------------------------------- parse
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
 
 
# ---------------------------------------------------------------- save
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
 
 
# ---------------------------------------------------------------- main loop
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
 
    last_first_id = None
    if resume and next_url:
        print(f"Resuming: {len(records)} records, {pages_done} pages done")
        ensure_window(next_url)
        navigate(next_url)
        last_first_id = wait_for_results()
    else:
        last_first_id = wait_for_results()  # use whatever page is already open
 
    start = time.time()
    added = 0
    current_url = next_url if (resume and next_url) else build_url()
 
    while True:
        if len(records) >= target:
            print(f"\nReached target of {target} records.")
            break
        if max_pages and pages_done >= max_pages:
            print(f"\nReached page limit of {max_pages}.")
            break
 
        # Recycle before Chrome degrades, not after it fails. A failed
        # recycle must never end the run — fall back to plain navigation.
        if pages_done and pages_done % RECYCLE_EVERY == 0 and current_url:
            print(f"  (recycling tab after {RECYCLE_EVERY} pages)")
            try:
                recycle_tab(current_url)
                last_first_id = wait_for_results()
            except RuntimeError as exc:
                print(f"  (recycle failed: {exc})")
                ensure_window(current_url)
                navigate(current_url)
                last_first_id = wait_for_results()
 
        try:
            html = get_html()
        except RuntimeError as exc:
            # Chrome stopped answering: rebuild and retry this page once.
            if not current_url:
                raise
            print(f"  (Chrome unresponsive: {exc})")
            print("  (rebuilding and retrying this page)")
            ensure_window(current_url)
            try:
                recycle_tab(current_url)
            except RuntimeError:
                navigate(current_url)
            last_first_id = wait_for_results()
            html = get_html()
 
        page_records = _parse_entry_page(html)
        if not page_records:
            # Almost always a render gap rather than the end of the results.
            # The last real page has rows but no Next link, which is handled
            # further down — so retry once before believing this.
            print("  (no records captured — re-reading the page)")
            time.sleep(2)
            html = get_html()
            page_records = _parse_entry_page(html)
        if not page_records:
            print("\nNo records after retry — stopping.")
            break
 
        fresh = [r for r in page_records if r["url"] not in seen]
        for r in fresh:
            seen.add(r["url"])
        records.extend(fresh)
        added += len(fresh)
        pages_done += 1
 
        next_url = _find_next_url(html)
 
        # Save after every page: an interruption costs one page, not the run.
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
        last_first_id = wait_for_results(last_first_id)
        current_url = next_url
 
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
 