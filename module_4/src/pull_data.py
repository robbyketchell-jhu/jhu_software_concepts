"""The ETL pipeline behind the Pull Data button.

:func:`pull_new_records` is the whole flow in one call:

1. read the result URLs already stored, so the scraper knows where to stop;
2. walk the newest Grad Cafe pages (:func:`src.scrape.scrape_pages`);
3. clean the rows (:mod:`src.clean`);
4. fill in the standardised program and university names
   (:mod:`src.standardize`); and
5. upsert them on ``p_id`` (:func:`src.load_data.load_records`).

Every collaborator is a parameter, so a test can hand in a fake scraper that
returns a fixed list of records and never touch the network.
"""

import sys

from . import config, load_data, scrape, standardize
from .clean import clean_scraped_record


def known_urls(url=None):
    """Return every Grad Cafe URL already stored.

    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: a set of URL strings.
    """
    load_data.ensure_table(url)
    with load_data.connect(url) as conn:
        rows = conn.execute("SELECT url FROM applicants WHERE url IS NOT NULL").fetchall()
    return {row[0] for row in rows}


def clean_records(records, call_llm=None):
    """Clean raw scraped records and standardise their names.

    Records that already carry an ``entry_id`` are assumed to be cleaned
    already and are passed through untouched.

    :param records: raw records from the scraper.
    :param call_llm: forwarded to :func:`src.standardize.standardize_rows`.
    :returns: the cleaned records.
    """
    cleaned = [
        record if "entry_id" in record else clean_scraped_record(record)
        for record in records
    ]
    return standardize.standardize_rows(cleaned, call_llm=call_llm)


def pull_new_records(scraper=None, loader=None, url=None, max_pages=25, log=None):
    """Scrape, clean and store newly submitted Grad Cafe entries.

    :param scraper: callable taking ``known_urls`` and returning raw records.
        Defaults to :func:`src.scrape.scrape_pages`.
    :param loader: callable taking the cleaned records and returning
        ``(upserted, skipped, total)``. Defaults to
        :func:`src.load_data.load_records`.
    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :param max_pages: page limit handed to the default scraper.
    :param log: callable receiving progress messages.
    :returns: a dict with the keys ``scraped``, ``inserted``, ``skipped`` and
        ``total_rows``.
    """
    log = log or (lambda message: None)

    def default_scraper(known):
        return scrape.scrape_pages(known_urls=known, max_pages=max_pages, log=log)

    scraper = scraper or default_scraper
    loader = loader or (lambda records: load_data.load_records(records, url=url))

    known = known_urls(url)
    log(f"{len(known)} entries already in the database")

    raw = list(scraper(known))
    log(f"scraped {len(raw)} new entries")
    if not raw:
        _, _, total = loader([])
        return {"scraped": 0, "inserted": 0, "skipped": 0, "total_rows": total}

    cleaned = clean_records(raw)
    inserted, skipped, total = loader(cleaned)
    log(f"inserted or updated {inserted} rows ({skipped} skipped without an id)")
    return {
        "scraped": len(raw),
        "inserted": inserted,
        "skipped": skipped,
        "total_rows": total,
    }


def main(argv=None):
    """Command line entry point for a manual pull.

    :param argv: argument list, defaulting to :data:`sys.argv` minus the
        program name. ``--max-pages N`` limits how far back to walk.
    :returns: a process exit code.
    """
    config.load_environment()
    argv = list(sys.argv[1:] if argv is None else argv)
    max_pages = 25
    if "--max-pages" in argv:
        max_pages = int(argv[argv.index("--max-pages") + 1])

    try:
        stats = pull_new_records(max_pages=max_pages, log=lambda m: print(m, flush=True))
    except (scrape.ScrapeError, OSError) as exc:
        print(f"Pull failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Pull finished: {stats['scraped']} scraped, {stats['inserted']} stored, "
        f"{stats['total_rows']} rows in total"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
