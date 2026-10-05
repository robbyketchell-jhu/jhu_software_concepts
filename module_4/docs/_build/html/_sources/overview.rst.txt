Overview and setup
==================

What the service does
---------------------

The application loads self-reported Grad Café admissions results into
PostgreSQL and publishes a single dynamic page that answers eleven analysis
questions about them. A *Pull Data* button fetches newly posted entries; an
*Update Analysis* button re-reads the database and redraws the page.

Requirements
------------

* Python 3.12
* PostgreSQL 14 or newer
* For live scraping only: macOS and Google Chrome (see
  :doc:`operations`). Nothing in the test suite needs either.

Install
-------

.. code-block:: console

   cd module_4
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 24 20 56

   * - Variable
     - Default
     - Meaning
   * - ``DATABASE_URL``
     - built from ``DB_*``
     - PostgreSQL connection URL, for example
       ``postgresql+psycopg://robby@localhost:5432/gradcafe``. ``postgres://``
       and ``postgresql://`` are accepted and rewritten onto the psycopg
       driver.
   * - ``TEST_DATABASE_URL``
     - ``DATABASE_URL``
     - Used only by the test suite. Whatever is given, the suite appends
       ``_test`` to the database name, so tests can never write to the
       development database.
   * - ``DB_USER``, ``DB_PASSWORD``, ``DB_HOST``, ``DB_PORT``, ``DB_NAME``
     - ``postgres``, empty, ``localhost``, ``5432``, ``gradcafe``
     - Used only when ``DATABASE_URL`` is unset. Kept for compatibility with
       the Module 3 ``.env`` file.
   * - ``PORT``
     - ``5000``
     - Port for the development server.
   * - ``FLASK_DEBUG``
     - unset
     - Set to ``1`` to run the development server in debug mode.

Credentials are never committed. ``.env`` is in ``.gitignore`` and every value
is read from the environment.

Set up the database
-------------------

.. code-block:: console

   # Homebrew
   brew install postgresql@17 && brew services start postgresql@17

   # or Docker
   docker run -d --name pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:17

Then create a ``.env`` beside the code:

.. code-block:: ini

   DATABASE_URL=postgresql+psycopg://robby@localhost:5432/gradcafe

Load the Module 2 dataset
-------------------------

.. code-block:: console

   python -m src.load_data path/to/llm_extend_applicant_data_clean.json

The loader creates the database and the ``applicants`` table if they do not
exist, then upserts every record on ``p_id``. Running it twice never
duplicates a row.

Run the analysis from the console
---------------------------------

.. code-block:: console

   python -m src.query_data                 # all eleven questions, raw SQL
   python -m src.query_data --question 8    # just one
   python -m src.orm_queries                # the same questions via the ORM
   python -m src.orm_queries --required     # 1, 4, 5, 8, 9 and one original

Run the web application
-----------------------

.. code-block:: console

   python -m src.flask_app        # http://127.0.0.1:5000
   PORT=5050 python -m src.flask_app

Run the tests
-------------

.. code-block:: console

   cd module_4
   pytest                                                        # the whole suite
   pytest -m "web or buttons or analysis or db or integration"   # identical selection
   pytest -m db                                                  # one subsystem

``pytest.ini`` turns on ``pytest-cov`` with ``--cov-fail-under=100``, so a run
that leaves any line of ``src`` untested fails. :doc:`testing` describes the
markers, the fixtures and the test doubles.
