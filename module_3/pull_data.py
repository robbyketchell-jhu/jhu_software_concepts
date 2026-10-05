"""
Module 3 - pull_data.py

Fetches newly submitted Grad Cafe entries with the Module 2 scraper and adds
them to the PostgreSQL applicants table. This is what the Flask "Pull Data"
button runs (as a subprocess), but it works on its own too:

    python pull_data.py                   # newest entries, up to 25 pages
    python pull_data.py --max-pages 5

How it works:
    1. Collect the URLs already in the database.
    2. Walk the Grad Cafe results pages (newest first) with scrape.py until a
       page contains nothing new, or --max-pages is reached.
    3. Clean the raw rows (clean.py), standardize program/university names
       (standardize.py), and upsert them (load_data.load_records).

Existing rows are never deleted. A re-scraped entry updates its own row via
the p_id upsert, so nothing is duplicated.

scrape.py drives a Chrome window that has already cleared Cloudflare's
check, so the same setup steps from Module 2 apply (see README).
"""

import argparse
import json
import os
import sys
import time

import psycopg

import scrape
from clean import clean_scraped_record
from load_data import conninfo, load_records
from standardize import HAVE_LLM, standardize_rows

HERE = os.path.dirname(os.path.abspath(__file__))
NEW_RECORDS_FILE = os.path.join(HERE, "pull_data_new.json")


def log(message):
    """Flush immediately so the Flask status endpoint can tail the log."""
    print(message, flush=True)


def known_urls():
    """Every Grad Cafe URL already stored, used to recognise 'old' entries."""
    with psycopg.connect(conninfo()) as conn:
        rows = conn.execute("SELECT url FROM applicants WHERE url IS NOT NULL").fetchall()
    return {row[0] for row in rows}


def scrape_new_records(known, max_pages, pause):
    """Walk the results pages newest-first and return records not in `known`."""
    new_records = []
    start_url = scrape.build_url()
    scrape.ensure_window(start_url)
    scrape.navigate(start_url)
    last_first_id = scrape.wait_for_results()

    for page in range(1, max_pages + 1):
        html = scrape.get_html()
        page_records = scrape.scrape_data(html)
        if not page_records:
            time.sleep(2)  # usually a render gap, not the end of the results
            html = scrape.get_html()
            page_records = scrape.scrape_data(html)
        if not page_records:
            log(f"page {page}: no records found, stopping")
            break

        fresh = [r for r in page_records if r["url"] not in known]
        known.update(r["url"] for r in fresh)
        new_records.extend(fresh)
        log(f"page {page}: {len(fresh)} new of {len(page_records)} entries "
            f"({len(new_records)} new so far)")

        if not fresh:
            log("Reached entries that are already in the database.")
            break

        next_url = scrape._find_next_url(html)
        if not next_url:
            log("No Next link, reached the end of the results.")
            break

        time.sleep(pause)
        scrape.navigate(next_url)
        last_first_id = scrape.wait_for_results(last_first_id)

    return new_records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-pages", type=int, default=25,
                        help="stop after this many results pages (default 25)")
    parser.add_argument("--pause", type=float, default=scrape.PAGE_PAUSE,
                        help="seconds to wait between pages")
    parser.add_argument("--robots-verified", action="store_true",
                        help="skip the automated robots.txt check (you verified it manually)")
    args = parser.parse_args()

    if sys.platform != "darwin":
        log("The Module 2 scraper drives Chrome via AppleScript and only runs on macOS.")
        return 1

    log("Pull Data started")
    log(f"Program/university standardizer: {'TinyLlama model' if HAVE_LLM else 'rules-based fallback'}")

    try:
        if args.robots_verified:
            log("robots.txt: manually verified (--robots-verified)")
        else:
            allowed, _ = scrape.check_robots()
            if not allowed:
                log("robots.txt disallows /survey, not scraping.")
                return 1

        known = known_urls()
        log(f"{len(known):,} entries already in the database")

        new_records = scrape_new_records(known, args.max_pages, args.pause)
    except psycopg.OperationalError as exc:
        log(f"Could not connect to PostgreSQL: {exc}")
        return 1
    except RuntimeError as exc:
        log(f"Scrape stopped: {exc}")
        return 1
    except KeyboardInterrupt:
        log("Interrupted before any new data was saved.")
        return 1

    if not new_records:
        log("No new entries found. The database is already up to date.")
        return 0

    # Keep the raw rows around for traceability (gitignored).
    with open(NEW_RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(new_records, f, indent=2, ensure_ascii=False)

    log(f"Cleaning {len(new_records)} new entries")
    cleaned = [clean_scraped_record(r) for r in new_records]
    log("Standardizing program and university names")
    standardize_rows(cleaned)

    try:
        upserted, skipped, total = load_records(cleaned)
    except psycopg.Error as exc:
        log(f"Database error while inserting new rows: {exc}")
        return 1

    log(f"Added {upserted} new entries ({skipped} skipped without an id)")
    log(f"applicants table now has {total:,} rows")
    log("Pull Data finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
