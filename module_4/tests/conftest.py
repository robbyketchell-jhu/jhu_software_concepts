"""Shared fixtures and test doubles for the Grad Cafe test suite.

Every test runs against a real PostgreSQL database, but never against the
development data: the URL comes from ``TEST_DATABASE_URL`` (falling back to
``DATABASE_URL``, then to a local default that ends in ``gradcafe_test``) and
the ``applicants`` table is truncated before each test.

No fixture reaches the network. The scraper is always a
:class:`FakeScraper`, so the suite is fast and deterministic.
"""

import os
import sys
from pathlib import Path

import psycopg
import pytest

MODULE_ROOT = Path(__file__).resolve().parent.parent
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from src import config, load_data, models  # noqa: E402
from src.flask_app import create_app  # noqa: E402

#: Used when neither TEST_DATABASE_URL nor DATABASE_URL is set.
DEFAULT_TEST_URL = "postgresql+psycopg://{user}@localhost:5432/gradcafe_test".format(
    user=os.getenv("USER", "postgres")
)


def _resolve_test_url():
    """Return the URL the suite should use, always a dedicated test database.

    :returns: a normalised SQLAlchemy URL string.
    """
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_TEST_URL
    url = config.normalize_url(url)
    name = config.database_name(url)
    if not name.endswith("_test"):
        url = config.url_for_database(f"{name}_test", url)
    return url


# --------------------------------------------------------------- database
@pytest.fixture(scope="session")
def database_url():
    """Create the test database if needed and expose its URL for the session.

    ``DATABASE_URL`` is exported for the whole session so that application
    code picks the test database up through the normal configuration path.

    :returns: the test database URL.
    """
    url = _resolve_test_url()
    os.environ["DATABASE_URL"] = url
    load_data.ensure_database(url)
    load_data.ensure_table(url)
    models.reset_engine()
    models.get_engine(url)
    yield url
    models.reset_engine()


@pytest.fixture
def db(database_url):
    """Truncate ``applicants`` and hand back an open psycopg connection.

    Each test therefore starts from an empty table.

    :returns: an open connection, closed on teardown.
    """
    with psycopg.connect(config.psycopg_conninfo(database_url), autocommit=True) as conn:
        conn.execute(load_data.CREATE_TABLE)
        conn.execute("TRUNCATE TABLE applicants")
        yield conn


@pytest.fixture
def row_count(database_url):
    """Return a callable giving the current ``applicants`` row count.

    :returns: a zero-argument callable returning an integer.
    """
    def count():
        with psycopg.connect(config.psycopg_conninfo(database_url)) as conn:
            return conn.execute("SELECT COUNT(*) FROM applicants").fetchone()[0]

    return count


# ------------------------------------------------------------ test doubles
#: Raw scraper records used across the suite. Shaped exactly like the output
#: of :func:`src.scrape.scrape_data`, with deliberate variety: an acceptance
#: and a rejection, an American and an international applicant, one row with
#: a full score set and one with almost nothing.
FAKE_SCRAPED_ROWS = [
    {
        "university": "Johns Hopkins University",
        "program": "Computer Science",
        "degree": "Masters",
        "date_added": "Sep 12, 2026",
        "url": "https://www.thegradcafe.com/result/9000001",
        "status": "Accepted",
        "semester_start": "Fall 2026",
        "student_type": "American",
        "gre": "168",
        "gre_v": "161",
        "gre_aw": "4.5",
        "gpa": "3.90",
        "comments": "Thrilled about this one.",
    },
    {
        "university": "Stanford University",
        "program": "Computer Science",
        "degree": "PhD",
        "date_added": "Sep 11, 2026",
        "url": "https://www.thegradcafe.com/result/9000002",
        "status": "Accepted",
        "semester_start": "Fall 2026",
        "student_type": "International",
        "gre": "170",
        "gre_v": "159",
        "gre_aw": "5.0",
        "gpa": "3.95",
        "comments": None,
    },
    {
        "university": "Carnegie Mellon University",
        "program": "Computer Science",
        "degree": "PhD",
        "date_added": "Sep 10, 2026",
        "url": "https://www.thegradcafe.com/result/9000003",
        "status": "Rejected",
        "semester_start": "Fall 2025",
        "student_type": "International",
        "gre": None,
        "gre_v": None,
        "gre_aw": None,
        "gpa": "3.40",
        "comments": None,
    },
    {
        "university": "Ithaca College",
        "program": "Speech Language Pathology",
        "degree": "Masters",
        "date_added": "Sep 09, 2026",
        "url": "https://www.thegradcafe.com/result/9000004",
        "status": "Accepted",
        "semester_start": "Fall 2025",
        "student_type": "American",
        "gre": None,
        "gre_v": None,
        "gre_aw": None,
        "gpa": None,
        "comments": None,
    },
]


class FakeScraper:
    """Stand-in for the live scraper.

    It records how it was called and returns a fixed list of records, so no
    test ever depends on the network or on Chrome.

    :param rows: records to return, defaulting to :data:`FAKE_SCRAPED_ROWS`.
    :param error: exception to raise instead of returning rows.
    """

    def __init__(self, rows=None, error=None):
        self.rows = FAKE_SCRAPED_ROWS if rows is None else rows
        self.error = error
        #: Number of times the scraper was invoked.
        self.calls = 0
        #: The ``known_urls`` set received on the most recent call.
        self.last_known = None

    def __call__(self, known_urls):
        self.calls += 1
        self.last_known = set(known_urls)
        if self.error is not None:
            raise self.error
        # Mirror the real scraper: entries already stored are not returned.
        return [row for row in self.rows if row["url"] not in self.last_known]


class RecordingLoader:
    """Loader wrapper that counts calls and remembers the rows it received.

    :param inner: the real loader to delegate to.
    :param error: exception to raise instead of loading.
    """

    def __init__(self, inner, error=None):
        self.inner = inner
        self.error = error
        #: Number of times the loader was invoked.
        self.calls = 0
        #: Records received on the most recent call.
        self.last_records = None

    def __call__(self, records):
        self.calls += 1
        self.last_records = list(records)
        if self.error is not None:
            raise self.error
        return self.inner(records)


@pytest.fixture
def fake_scraper():
    """Return a :class:`FakeScraper` over :data:`FAKE_SCRAPED_ROWS`."""
    return FakeScraper()


@pytest.fixture
def recording_loader(database_url):
    """Return a :class:`RecordingLoader` wrapping the real loader."""
    return RecordingLoader(lambda records: load_data.load_records(records, url=database_url))


#: Analysis payload used by tests that do not need the database. It mirrors
#: the shape of :func:`src.orm_queries.collect_results`, including a
#: percentage that must survive rendering with exactly two decimals.
STATIC_ANALYSIS = [
    {
        "number": 1,
        "title": "How many entries are from applicants who applied for Fall 2026?",
        "kind": "lines",
        "lines": [("Fall 2026 applicant count", "19,290")],
    },
    {
        "number": 2,
        "title": "Among entries with a nationality classification, what percentage "
                 "are international?",
        "kind": "lines",
        "lines": [("Percent international", "50.09%")],
    },
    {
        "number": 5,
        "title": "What percentage of Fall 2025 entries are acceptances?",
        "kind": "lines",
        "lines": [("Fall 2025 acceptance percentage", "39.28%")],
    },
    {
        "number": 10,
        "title": "Original question 1: acceptance rate by nationality",
        "kind": "table",
        "columns": ["Nationality", "Entries", "Accepted", "Acceptance percent"],
        "rows": [
            ["American", "17,726", "6,510", "36.73%"],
            ["International", "14,791", "5,066", "34.25%"],
        ],
    },
]


# ------------------------------------------------------------------- app
@pytest.fixture
def app(database_url, fake_scraper, recording_loader):
    """A testable app wired to fakes and to the real test database.

    ``run_async`` is ``False``, so a Pull Data request finishes inside the
    request and the assertions need no waiting.

    :returns: the Flask application.
    """
    application = create_app(
        {"TESTING": True},
        scraper=fake_scraper,
        loader=recording_loader,
        run_async=False,
        database_url=database_url,
    )
    application.config["FAKE_SCRAPER"] = fake_scraper
    application.config["RECORDING_LOADER"] = recording_loader
    return application


@pytest.fixture
def client(app):
    """Flask test client for :func:`app`."""
    return app.test_client()


@pytest.fixture
def static_app():
    """An app whose analysis provider returns :data:`STATIC_ANALYSIS`.

    Useful for page-rendering and formatting tests that should not depend on
    database contents.

    :returns: the Flask application.
    """
    return create_app(
        {"TESTING": True},
        scraper=FakeScraper(),
        loader=lambda records: (len(records), 0, len(records)),
        analysis=lambda: STATIC_ANALYSIS,
        run_async=False,
    )


@pytest.fixture
def static_client(static_app):
    """Flask test client for :func:`static_app`."""
    return static_app.test_client()
