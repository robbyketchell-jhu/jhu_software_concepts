Architecture
============

Three layers, each with one job.

.. code-block:: text

   Grad Café  ──▶  browser.py ──▶ scrape.py ──▶ clean.py ──▶ standardize.py
                   (Chrome)       (parse)       (normalise)   (canonical names)
                                                                    │
                                                                    ▼
                                                              load_data.py
                                                            (psycopg upsert)
                                                                    │
                                                                    ▼
                                                      PostgreSQL  applicants
                                                                    │
                                        ┌───────────────────────────┴───────────┐
                                        ▼                                       ▼
                                 query_data.py                           orm_queries.py
                                  (raw SQL)                             (SQLAlchemy ORM)
                                                                                │
                                                                                ▼
                                                                         flask_app.py
                                                                     (Analysis page + API)

Web layer
---------

:mod:`src.flask_app` builds the application with a ``create_app`` factory. It
renders the analysis page and exposes the two button endpoints plus a status
endpoint. Two pieces of state matter:

:class:`src.flask_app.PullState`
   The busy flag. ``begin()`` is atomic, so only one pull runs at a time, and
   ``snapshot()`` makes the state observable without waiting on anything.

:class:`src.flask_app.Services`
   The collaborators a request may need: the scraper, the loader and the
   analysis provider. All three are constructor arguments, which is what lets
   the tests inject fakes.

Page reads always go through the ORM. The route calls
:func:`src.orm_queries.analysis_results`, so the browser never sees a number
that did not come from the ``Applicant`` model.

ETL layer
---------

:mod:`src.browser`
   Everything that talks to Chrome through AppleScript. Grad Café sits behind
   Cloudflare, so pages are read out of a window the user has already cleared.
   The scraper only uses a six-method interface, which a fake can satisfy.

:mod:`src.scrape`
   URL building and ``robots.txt`` checking with ``urllib3``, HTML parsing
   with BeautifulSoup, and the paging loop. The loop takes the browser as a
   parameter, so no test ever launches anything.

:mod:`src.clean`
   Converts raw scraped records into the loader's shape: placeholders become
   ``NULL``, dates are parsed, and numbers are range-checked. Out-of-range
   values are stored as missing rather than kept, because a "GRE Quantitative"
   of 320 is a combined score and would otherwise distort the averages.

:mod:`src.standardize`
   Fills in ``llm_generated_program`` and ``llm_generated_university``. Uses
   the Module 2 TinyLlama model when it is installed, otherwise a rules-first
   fallback that splits, expands abbreviations and fuzzy-matches against the
   canonical name lists.

:mod:`src.pull_data`
   Ties the above together: read the stored URLs, scrape what is new, clean,
   standardise, upsert. Every collaborator is a parameter.

Database layer
--------------

:mod:`src.config`
   Turns ``DATABASE_URL`` (or the individual ``DB_*`` variables) into either a
   SQLAlchemy URL or a libpq conninfo string.

:mod:`src.models`
   The SQLAlchemy 2.x ``Applicant`` model over the ``applicants`` table, plus
   a lazily built engine and session factory. The engine is resettable so a
   test can repoint it at a throwaway database.

:mod:`src.load_data`
   Creates the table and upserts rows with psycopg. The upsert is
   ``ON CONFLICT (p_id) DO UPDATE``, which is the uniqueness policy the whole
   system relies on.

:mod:`src.query_data`
   The eleven questions as raw SQL, plus ``fetch_applicant`` and
   ``fetch_applicants``, which return dictionaries keyed by the required
   Module 3 fields.

:mod:`src.orm_queries`
   The same questions expressed with ``select()``, ``where()``, ``func``,
   ``and_()`` and ``or_()``. No ``text()`` and no cursors anywhere.

The schema
----------

One table, ``applicants``, with ``p_id`` as the primary key.

.. list-table::
   :header-rows: 1
   :widths: 34 24 42

   * - Column
     - Type
     - Meaning
   * - ``p_id``
     - ``integer``
     - Grad Café entry id; primary key and uniqueness key
   * - ``program``
     - ``text``
     - University and department, as posted
   * - ``comments``
     - ``text``
     - Applicant comments
   * - ``date_added``
     - ``date``
     - When the entry appeared
   * - ``url``
     - ``text``
     - Link to the entry
   * - ``status``
     - ``text``
     - Accepted / Rejected / Wait listed / Interview
   * - ``term``
     - ``text``
     - Intended start term
   * - ``us_or_international``
     - ``text``
     - American / International / Other
   * - ``gpa``
     - ``double precision``
     - Grade point average, 0-4.0
   * - ``gre``, ``gre_v``
     - ``double precision``
     - GRE Quantitative and Verbal, 130-170
   * - ``gre_aw``
     - ``double precision``
     - GRE Analytical Writing, 0-6
   * - ``degree``
     - ``text``
     - Degree type
   * - ``llm_generated_program``
     - ``text``
     - Standardised department
   * - ``llm_generated_university``
     - ``text``
     - Standardised university
