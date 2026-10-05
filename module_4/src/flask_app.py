"""Flask web layer: the Analysis page and its two buttons.

The app is built by :func:`create_app`, which takes every collaborator as a
keyword argument. A test can therefore hand in a fake scraper, a fake loader
and a fake analysis provider and exercise the whole surface without a network
or a browser.

Routes
------

==========================  ======  =========================================
Route                       Method  Behaviour
==========================  ======  =========================================
``/``                       GET     Redirects to ``/analysis``.
``/analysis``               GET     Renders the analysis page (HTTP 200).
``/pull-data``              POST    Runs the ETL pipeline. ``202`` with
                                    ``{"ok": true}``, or ``409`` with
                                    ``{"busy": true}`` while a pull runs.
``/update-analysis``        POST    Re-reads the database. ``200`` with
                                    ``{"ok": true}``, or ``409`` with
                                    ``{"busy": true}`` while a pull runs.
``/status``                 GET     JSON snapshot of the busy state.
==========================  ======  =========================================

Busy state is held in :class:`PullState`, which is observable (``snapshot()``)
and directly controllable (``begin()`` / ``finish()``). Tests never sleep;
they flip the state and assert on the response.
"""

import threading
from datetime import datetime, timezone

from flask import Flask, current_app, jsonify, redirect, render_template, url_for

from . import config
from .orm_queries import analysis_results
from .pull_data import pull_new_records

#: Stable selector for the Pull Data button.
PULL_BUTTON_TESTID = "pull-data-btn"
#: Stable selector for the Update Analysis button.
UPDATE_BUTTON_TESTID = "update-analysis-btn"


def _now():
    """Return an ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PullState:
    """Observable busy flag guarding the Pull Data pipeline.

    One pull runs at a time. :meth:`begin` is atomic, so two concurrent
    requests cannot both start a scrape, and the state is plain data that a
    test can inspect or set without waiting on anything.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.running = False
        self.started_at = None
        self.finished_at = None
        self.last_result = None
        self.last_error = None
        #: Incremented every time the analysis is actually recomputed.
        self.analysis_version = 0
        #: Timestamp of the most recent successful analysis refresh.
        self.analysis_refreshed_at = None

    def begin(self):
        """Mark a pull as started.

        :returns: ``True`` when this caller acquired the slot, ``False`` when
            a pull was already running.
        """
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.started_at = _now()
            self.finished_at = None
            self.last_error = None
            return True

    def finish(self, result=None, error=None):
        """Mark the running pull as finished.

        :param result: the pipeline's stats dict on success.
        :param error: the error message on failure.
        """
        with self._lock:
            self.running = False
            self.finished_at = _now()
            self.last_result = result
            self.last_error = error

    def note_analysis(self):
        """Record that the analysis was recomputed."""
        self.analysis_version += 1
        self.analysis_refreshed_at = _now()

    def snapshot(self):
        """Return the state as a JSON-serialisable dict.

        :returns: a dict describing the current and most recent pull.
        """
        return {
            "running": self.running,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_result": self.last_result,
            "last_error": self.last_error,
            "analysis_version": self.analysis_version,
            "analysis_refreshed_at": self.analysis_refreshed_at,
        }


class Services:
    """Container for the collaborators a request may need.

    :param scraper: callable taking the set of known URLs and returning raw
        records, or ``None`` to use the real scraper.
    :param loader: callable taking cleaned records and returning
        ``(upserted, skipped, total)``, or ``None`` for the real loader.
    :param analysis: zero-argument callable returning the analysis results,
        defaulting to :func:`src.orm_queries.analysis_results`.
    :param run_async: when ``True`` a pull runs on a background thread, which
        is what the real app wants; tests pass ``False`` so the pull completes
        within the request and the assertions stay deterministic.
    :param max_pages: page limit handed to the real scraper.
    """

    def __init__(self, scraper=None, loader=None, analysis=None, run_async=True,
                 max_pages=25):
        self.scraper = scraper
        self.loader = loader
        self.analysis = analysis or analysis_results
        self.run_async = run_async
        self.max_pages = max_pages
        self.state = PullState()

    def run_pull(self):
        """Run the ETL pipeline once with the configured collaborators.

        :returns: the pipeline's stats dict.
        """
        return pull_new_records(
            scraper=self.scraper,
            loader=self.loader,
            max_pages=self.max_pages,
        )


def get_services(app=None):
    """Return the :class:`Services` attached to *app*.

    :param app: the Flask app, defaulting to the current one.
    :returns: the services container.
    """
    return (app or current_app).extensions["gradcafe"]


def create_app(config_object=None, *, scraper=None, loader=None, analysis=None,
               run_async=True, max_pages=25, database_url=None):
    """Build and return the Flask application.

    :param config_object: mapping of Flask config values to apply, e.g.
        ``{"TESTING": True}``.
    :param scraper: fake or real scraper, see :class:`Services`.
    :param loader: fake or real loader, see :class:`Services`.
    :param analysis: analysis provider, see :class:`Services`.
    :param run_async: whether Pull Data runs on a background thread.
    :param max_pages: page limit handed to the real scraper.
    :param database_url: overrides ``DATABASE_URL`` for this app's ORM engine.
    :returns: the configured :class:`flask.Flask` application.
    """
    config.load_environment()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY="gradcafe-analysis-page",  # signs flash cookies only
        DATABASE_URL=database_url or config.database_url(),
        JSON_SORT_KEYS=False,
    )
    if config_object:
        app.config.update(config_object)

    app.extensions["gradcafe"] = Services(
        scraper=scraper,
        loader=loader,
        analysis=analysis,
        run_async=run_async,
        max_pages=max_pages,
    )

    register_routes(app)
    return app


def register_routes(app):
    """Attach every route to *app*.

    :param app: the Flask application.
    """

    @app.get("/")
    def home():
        """Redirect the site root to the analysis page."""
        return redirect(url_for("analysis"))

    @app.get("/analysis")
    def analysis():
        """Render the analysis page.

        :returns: the rendered page with HTTP 200, or an error banner with
            HTTP 200 when the database cannot be read.
        """
        services = get_services()
        error = None
        results = []
        try:
            results = services.analysis()
            services.state.note_analysis()
        except Exception as exc:  # surfaced to the user, not a crash
            error = (
                f"Could not read the analysis from PostgreSQL "
                f"({exc.__class__.__name__}). Check DATABASE_URL and that the "
                f"database is running."
            )
        return render_template(
            "index.html",
            results=results,
            error=error,
            state=services.state.snapshot(),
            pull_testid=PULL_BUTTON_TESTID,
            update_testid=UPDATE_BUTTON_TESTID,
        )

    @app.post("/pull-data")
    def pull_data_route():
        """Start a Pull Data run.

        :returns: ``202`` with ``{"ok": true}`` when the pull was accepted,
            ``409`` with ``{"busy": true}`` when one is already running, or
            ``500`` with ``{"ok": false}`` when the pipeline raised.
        """
        services = get_services()
        state = services.state
        if not state.begin():
            return jsonify({"ok": False, "busy": True,
                            "message": "A data pull is already running."}), 409

        if services.run_async:  # pragma: no cover - threading is not under test
            threading.Thread(target=_run_pull_safely, args=(services,),
                             daemon=True).start()
            return jsonify({"ok": True, "busy": True, "started": True,
                            "message": "Pull Data started."}), 202

        try:
            result = services.run_pull()
        except Exception as exc:
            state.finish(error=str(exc))
            return jsonify({"ok": False, "busy": False, "error": str(exc),
                            "message": "Pull Data failed; no rows were changed."}), 500

        state.finish(result=result)
        return jsonify({"ok": True, "busy": False, "result": result,
                        "message": "Pull Data finished."}), 202

    @app.post("/update-analysis")
    def update_analysis_route():
        """Recompute the analysis from the current database contents.

        Never starts a scrape.

        :returns: ``200`` with ``{"ok": true}``, ``409`` with
            ``{"busy": true}`` while a pull is running, or ``500`` with
            ``{"ok": false}`` when the query layer raised.
        """
        services = get_services()
        state = services.state
        if state.running:
            return jsonify({
                "ok": False,
                "busy": True,
                "message": "New data is being retrieved; the analysis was not updated.",
            }), 409

        try:
            results = services.analysis()
        except Exception as exc:
            return jsonify({"ok": False, "busy": False, "error": str(exc),
                            "message": "Could not refresh the analysis."}), 500

        state.note_analysis()
        return jsonify({
            "ok": True,
            "busy": False,
            "questions": len(results),
            "analysis_version": state.analysis_version,
            "message": "Analysis refreshed from PostgreSQL.",
        }), 200

    @app.get("/status")
    def status():
        """Return the busy-state snapshot as JSON."""
        return jsonify(get_services().state.snapshot()), 200


def _run_pull_safely(services):  # pragma: no cover - background thread
    """Run a pull and record the outcome, swallowing any exception.

    :param services: the services container owning the state.
    """
    try:
        result = services.run_pull()
    except Exception as exc:
        services.state.finish(error=str(exc))
    else:
        services.state.finish(result=result)


def main():  # pragma: no cover - development server entry point
    """Run the development server."""
    import os

    app = create_app()
    app.run(host="127.0.0.1", port=int(os.getenv("PORT", "5000")),
            debug=os.getenv("FLASK_DEBUG") == "1")


if __name__ == "__main__":  # pragma: no cover
    main()
