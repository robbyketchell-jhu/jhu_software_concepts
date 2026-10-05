Testing guide
=============

.. code-block:: console

   cd module_4
   pytest

That runs all 285 tests with coverage and fails if coverage of ``src`` drops
below 100 percent.

Markers
-------

Every test carries at least one marker. There are no unmarked tests, so the
marker expression below selects the entire suite:

.. code-block:: console

   pytest -m "web or buttons or analysis or db or integration"

.. list-table::
   :header-rows: 1
   :widths: 16 44 40

   * - Marker
     - Covers
     - Files
   * - ``web``
     - App factory, routes, page rendering, HTML structure
     - ``test_flask_page.py``
   * - ``buttons``
     - The two button endpoints, busy gating, error paths
     - ``test_buttons.py``
   * - ``analysis``
     - Labels, two-decimal formatting, the SQL and ORM query layers
     - ``test_analysis_format.py``, ``test_query_layer.py``
   * - ``db``
     - Schema, inserts, idempotency, selects, and the ETL that feeds them
     - ``test_db_insert.py``, ``test_etl_units.py``, ``test_scrape.py``,
       ``test_config_and_models.py``, ``test_cli_entrypoints.py``
   * - ``integration``
     - End-to-end pull, update and render flows
     - ``test_integration_end_to_end.py``

Run one subsystem at a time:

.. code-block:: console

   pytest -m web
   pytest -m "db and not integration"

The database the tests use
--------------------------

The suite resolves its URL from ``TEST_DATABASE_URL``, then ``DATABASE_URL``,
then a local default, and then **appends** ``_test`` to the database name if
it is not already there. A run against ``.../gradcafe`` therefore uses
``gradcafe_test``. The development data cannot be reached by a test.

The ``db`` fixture truncates ``applicants`` before handing over a connection,
so every test starts from an empty table.

Stable selectors
----------------

UI assertions use ``data-testid`` attributes rather than CSS classes or text
positions, so restyling the page does not break the tests.

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Selector
     - Element
   * - ``pull-data-btn``
     - The Pull Data button
   * - ``update-analysis-btn``
     - The Update Analysis button
   * - ``analysis-results``
     - Container holding every result card
   * - ``result-<n>``
     - The card for question ``n``
   * - ``answer-value``
     - Each rendered answer value, including table cells
   * - ``job-status``
     - The pull progress line
   * - ``analysis-version``
     - The observable analysis counter in the header
   * - ``analysis-error``
     - The banner shown when the database cannot be read

The two button selectors are exported as
:data:`src.flask_app.PULL_BUTTON_TESTID` and
:data:`src.flask_app.UPDATE_BUTTON_TESTID`, so a test never hard-codes them.

Fixtures
--------

Defined in ``tests/conftest.py``.

.. list-table::
   :header-rows: 1
   :widths: 24 76

   * - Fixture
     - What it gives you
   * - ``database_url``
     - Session scoped. Creates the test database and table, exports
       ``DATABASE_URL`` and points the ORM engine at it.
   * - ``db``
     - Truncates ``applicants`` and yields an open psycopg connection.
   * - ``row_count``
     - A callable returning the current row count.
   * - ``fake_scraper``
     - A :class:`FakeScraper` over the four canned records.
   * - ``recording_loader``
     - The real loader, wrapped so a test can see what it received.
   * - ``app`` / ``client``
     - An app wired to the fakes and the test database, with
       ``run_async=False``.
   * - ``static_app`` / ``static_client``
     - An app whose analysis provider returns a fixed payload, for tests that
       should not depend on database contents.

Test doubles
------------

``FakeScraper``
   Returns a fixed list of raw records and records how it was called. It
   mirrors the real scraper by filtering out URLs that are already known, so
   idempotency tests behave the way production does. Set ``error=`` to make it
   raise.

``RecordingLoader``
   Wraps the real loader, counting calls and keeping the rows it was handed,
   so a test can assert that the scraper's output actually reached the loader.

``FakeBrowser`` (in ``test_scrape.py``)
   Implements the six-method browser interface over canned HTML. Nothing
   launches Chrome.

``FakeRunner`` (in ``test_scrape.py``)
   Stands in for ``subprocess.run`` so the AppleScript driver can be tested
   without ``osascript``.

``FakeHttp`` / ``FakeResponse`` (in ``test_scrape.py``)
   Stand in for ``urllib3`` when checking ``robots.txt``.

Determinism
-----------

* No test reaches the network or launches a browser.
* No test calls ``sleep``. Busy state is exercised by calling
  :meth:`src.flask_app.PullState.begin` directly, and every waiting loop takes
  injectable ``clock`` and ``sleeper`` callables.
* Apps under test use ``run_async=False``, so a pull finishes inside the
  request.
* The whole suite runs in a few seconds.

Coverage
--------

.. code-block:: console

   pytest                       # enforces 100 percent
   coverage report --show-missing
   coverage html && open htmlcov/index.html

The committed summary lives in ``module_4/coverage_summary.txt``.
