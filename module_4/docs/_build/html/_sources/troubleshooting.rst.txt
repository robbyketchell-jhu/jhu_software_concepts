Troubleshooting
===============

Local development
-----------------

**``connection refused`` on port 5432**
   PostgreSQL is not running. ``brew services start postgresql@17``, or start
   the Docker container. Check with
   ``pg_isready -h localhost -p 5432``.

**``database "gradcafe" does not exist``**
   Run ``python -m src.load_data <file>`` once; it creates the database and
   the table. Or create it by hand with ``createdb gradcafe``.

**``role "postgres" does not exist`` on macOS**
   Homebrew creates a role named after your macOS user, not ``postgres``. Put
   your own name in ``DATABASE_URL``, for example
   ``postgresql+psycopg://robby@localhost:5432/gradcafe``.

**The page shows "Could not read the analysis from PostgreSQL"**
   The web layer could not reach the database. Confirm ``DATABASE_URL``, that
   the server is up, and that the ``applicants`` table exists.

**Every number on the page is N/A**
   The table is empty. Load the Module 2 dataset, or press Pull Data.

**Pull Data does nothing**
   A pull is already running; the response is 409 and the button is disabled
   until ``GET /status`` reports ``running: false``. If a live scrape fails
   immediately, work through :doc:`operations` - Chrome must be frontmost with
   the Cloudflare check cleared.

Tests
-----

**``Coverage failure: total of N is less than fail-under=100``**
   Something in ``src`` is not exercised. ``coverage report --show-missing``
   names the lines; ``coverage html`` gives a browsable report.

**``Module src was never imported``**
   pytest was started from the wrong directory. Run it from ``module_4``.

**Tests cannot connect to PostgreSQL**
   The suite needs a real server. Set ``TEST_DATABASE_URL`` if yours is not on
   ``localhost:5432``. The suite always appends ``_test`` to the database
   name, so it never touches development data.

**A test leaves rows behind**
   Request the ``db`` fixture. It truncates ``applicants`` before the test
   body runs; a test that writes rows without it inherits whatever the
   previous test left.

Continuous integration
----------------------

**The Postgres service is not ready**
   The workflow already waits on ``pg_isready`` through the service health
   check. If a job still fails on connection, raise ``--health-retries``.

**``psycopg`` fails to build**
   Install the binary wheel. ``requirements.txt`` pins
   ``psycopg[binary]``, which needs no local libpq.

**Coverage differs between local and CI**
   Usually a platform-specific branch. The suite avoids them by injecting
   clocks, sleepers and subprocess runners rather than checking
   ``sys.platform``.

Documentation
-------------

**autodoc cannot import src**
   ``docs/conf.py`` puts ``module_4`` on ``sys.path``. Build from inside
   ``module_4/docs`` so the relative path resolves.

**Read the Docs build fails on a missing dependency**
   The build installs ``module_4/requirements.txt`` via
   ``.readthedocs.yaml``. Anything imported at module scope must be listed
   there.
