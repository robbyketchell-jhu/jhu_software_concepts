Operational notes
=================

Busy-state policy
-----------------

One pull at a time, enforced by :class:`src.flask_app.PullState`.

* ``POST /pull-data`` while idle takes the slot and returns **202** with
  ``{"ok": true}``.
* ``POST /pull-data`` while a pull runs returns **409** with
  ``{"busy": true}`` and does not start anything.
* ``POST /update-analysis`` while a pull runs returns **409** with
  ``{"busy": true}`` and performs no update. The running pull is left alone.
* ``POST /update-analysis`` while idle returns **200**, recomputes the
  analysis and increments ``analysis_version``.
* ``GET /status`` always answers, running or not.

``begin()`` takes a lock and checks the flag inside it, so two requests
arriving together cannot both start a scrape. The flag is released in
``finish()`` on both the success and the failure path, so a failed pull never
wedges the application.

In production the pull runs on a background thread and the request returns
immediately. Tests build the app with ``run_async=False`` so the work happens
inside the request and assertions need no waiting.

Idempotency and uniqueness
--------------------------

The uniqueness key is ``p_id``, the Grad Café entry id, which is also the
primary key. It is read from the record's ``entry_id`` or parsed out of its
``/result/<id>`` URL.

Writes are ``INSERT ... ON CONFLICT (p_id) DO UPDATE``, which means:

* re-pulling the same entries leaves the row count unchanged;
* a re-scraped entry whose status has changed updates in place; and
* duplicates inside a single batch collapse before the insert, because the
  loader keys them into a dict first.

The scraper also receives the set of stored URLs and stops at the first page
with nothing new, so an incremental pull reads one or two pages rather than
the whole archive.

Data quality rules
------------------

Values outside a plausible range are stored as ``NULL`` rather than kept:

.. list-table::
   :header-rows: 1
   :widths: 34 22 44

   * - Field
     - Accepted range
     - Typical rejected value
   * - ``gpa``
     - 0.0 to 4.0
     - 9.2, a 10-point scale
   * - ``gre``, ``gre_v``
     - 130 to 170
     - 320, a combined score
   * - ``gre_aw``
     - 0.0 to 6.0
     - 10

A record with no usable id is skipped and counted, never written.

Failure handling
----------------

* A loader or scraper exception returns **500** with ``{"ok": false}`` and the
  error message. The batch runs in one transaction, so nothing is partly
  written.
* A database read failure on ``GET /analysis`` renders the page with an error
  banner rather than a stack trace, so the buttons stay usable.
* The scraper distinguishes a render gap from the end of the results by
  re-reading a blank page once before believing it.
* A failed Chrome tab recycle falls back to plain navigation rather than
  ending a long run.

Running a live pull
-------------------

Grad Café is behind Cloudflare, so the scraper drives a Chrome window that has
already been cleared by hand:

1. Chrome: **View → Developer → Allow JavaScript from Apple Events**
2. Open https://www.thegradcafe.com/survey and clear the human check
3. Leave that window frontmost, then press **Pull Data** or run
   ``python -m src.pull_data --max-pages 5``

``robots.txt`` is fetched and checked before any page is read.
