"""
Module 3 - app.py

Flask front end for the Grad Cafe analysis.

    python app.py            # http://127.0.0.1:5000

Routes
    GET  /                 Analysis page. Every number on it is read from
                           PostgreSQL through the SQLAlchemy Applicant model
                           (orm_queries.collect_results).
    POST /pull-data        Starts pull_data.py as a subprocess, unless one is
                           already running.
    POST /update-analysis  Re-queries the database and re-renders. Never starts
                           a scrape. If a Pull Data run is active it says so.
    GET  /status           JSON used by the page to show live scrape progress.
"""

import os
import subprocess
import sys
import threading
from datetime import datetime

from flask import Flask, flash, jsonify, redirect, render_template, request, url_for
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from models import Applicant, SessionLocal
from orm_queries import collect_results

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(HERE, "pull_data.log")
DEFAULT_MAX_PAGES = int(os.getenv("PULL_MAX_PAGES", "25"))

app = Flask(__name__)
# Only used to sign the flash-message cookie; not a credential.
app.secret_key = os.getenv("FLASK_SECRET_KEY", "module-3-analysis-page")


class ScrapeJob:
    """
    Tracks the single Pull Data subprocess. The lock makes start() atomic, so
    two quick clicks (or two browser tabs) cannot launch two scrapers.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.process = None
        self.started = None
        self.finished = None
        self.returncode = None

    def _running_locked(self):
        if self.process is None:
            return False
        if self.process.poll() is None:
            return True
        if self.finished is None:  # first time we notice it ended
            self.finished = datetime.now()
            self.returncode = self.process.returncode
        return False

    def is_running(self):
        with self._lock:
            return self._running_locked()

    def start(self, max_pages=DEFAULT_MAX_PAGES):
        """Returns True if a scrape was started, False if one was already running."""
        with self._lock:
            if self._running_locked():
                return False
            log = open(LOG_FILE, "w", encoding="utf-8")
            self.process = subprocess.Popen(
                [sys.executable, "-u", "pull_data.py", "--max-pages", str(max_pages)],
                cwd=HERE,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            log.close()  # the child holds its own handle
            self.started = datetime.now()
            self.finished = None
            self.returncode = None
            return True

    def log_tail(self, lines=6):
        try:
            with open(LOG_FILE, encoding="utf-8") as f:
                return [line.rstrip() for line in f.readlines()[-lines:]]
        except FileNotFoundError:
            return []

    def summary(self):
        running = self.is_running()
        return {
            "running": running,
            "started": self.started.strftime("%H:%M:%S") if self.started else None,
            "finished": self.finished.strftime("%H:%M:%S") if self.finished else None,
            "returncode": self.returncode,
            "succeeded": (self.returncode == 0) if self.finished else None,
            "log": self.log_tail(),
        }


scrape_job = ScrapeJob()


def database_overview(session):
    """Row count and newest entry date for the page header (ORM read)."""
    total, newest = session.execute(
        select(func.count(), func.max(Applicant.date_added)).select_from(Applicant)
    ).one()
    return {"total": f"{total:,}", "newest": newest.isoformat() if newest else "n/a"}


@app.route("/")
def index():
    results = []
    overview = None
    error = None
    try:
        with SessionLocal() as session:
            overview = database_overview(session)
            results = collect_results(session)
    except SQLAlchemyError as exc:
        error = f"Could not read from PostgreSQL: {exc.__class__.__name__}. Check the .env settings and that the database is running."
        app.logger.exception("database read failed")

    return render_template(
        "index.html",
        results=results,
        overview=overview,
        error=error,
        job=scrape_job.summary(),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


@app.post("/pull-data")
def pull_data():
    if scrape_job.start():
        flash("Pull Data started. New Grad Cafe entries are being retrieved in the background; "
              "click Update Analysis when it finishes to see them.", "info")
    else:
        flash("A Pull Data run is already in progress. Wait for it to finish before starting another.",
              "warning")
    return redirect(url_for("index"))


@app.post("/update-analysis")
def update_analysis():
    if scrape_job.is_running():
        flash("New data is currently being retrieved from Grad Cafe. The results below reflect the "
              "data already in PostgreSQL; the scrape was left running and will not be interrupted.",
              "warning")
    else:
        job = scrape_job.summary()
        if job["finished"] and job["succeeded"] is False:
            flash(f"The last Pull Data run ended with an error (see the log below). "
                  f"Analysis refreshed from the current database contents.", "error")
        else:
            flash(f"Analysis refreshed from PostgreSQL at {datetime.now().strftime('%H:%M:%S')}.", "success")
    return redirect(url_for("index"))


@app.get("/status")
def status():
    return jsonify(scrape_job.summary())


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=os.getenv("FLASK_DEBUG") == "1")
