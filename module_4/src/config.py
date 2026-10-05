"""Database configuration.

The single source of truth is the ``DATABASE_URL`` environment variable, for
example::

    DATABASE_URL=postgresql+psycopg://robby@localhost:5432/gradcafe

When ``DATABASE_URL`` is not set the URL is assembled from the individual
``DB_*`` variables that Module 3 used, so an existing ``.env`` keeps working.
Nothing in this module ever hard-codes a credential; every value comes from
the environment.
"""

import os
from urllib.parse import quote, urlsplit

from dotenv import load_dotenv

#: SQLAlchemy driver used for every connection URL this module produces.
DRIVER = "postgresql+psycopg"

#: Fallback values for the individual ``DB_*`` variables.
DEFAULTS = {
    "DB_NAME": "gradcafe",
    "DB_USER": "postgres",
    "DB_PASSWORD": "",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
}


def load_environment(dotenv_path=None):
    """Load a ``.env`` file if one is present.

    :param dotenv_path: explicit path to a ``.env`` file, or ``None`` to let
        python-dotenv search upwards from the working directory.
    :returns: ``True`` when a file was found and loaded.
    """
    return load_dotenv(dotenv_path, override=False)


def _from_parts():
    """Build a SQLAlchemy URL out of the individual ``DB_*`` variables."""
    user = os.getenv("DB_USER", DEFAULTS["DB_USER"])
    password = os.getenv("DB_PASSWORD", DEFAULTS["DB_PASSWORD"])
    host = os.getenv("DB_HOST", DEFAULTS["DB_HOST"])
    port = os.getenv("DB_PORT", DEFAULTS["DB_PORT"])
    name = os.getenv("DB_NAME", DEFAULTS["DB_NAME"])

    credentials = quote(user, safe="")
    if password:
        credentials = f"{credentials}:{quote(password, safe='')}"
    return f"{DRIVER}://{credentials}@{host}:{port}/{name}"


def normalize_url(url):
    """Return *url* with the SQLAlchemy psycopg driver spelled out.

    ``postgres://`` and ``postgresql://`` URLs (what hosting providers and the
    GitHub Actions Postgres service hand out) are rewritten to
    ``postgresql+psycopg://`` so SQLAlchemy picks the installed driver.

    :param url: any PostgreSQL connection URL.
    :returns: the normalised URL.
    """
    for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
        if url.startswith(prefix):
            return DRIVER + "://" + url[len(prefix):]
    return url


def database_url():
    """Return the SQLAlchemy URL for the application database.

    :returns: a ``postgresql+psycopg://`` URL string.
    """
    url = os.getenv("DATABASE_URL")
    return normalize_url(url) if url else _from_parts()


def psycopg_conninfo(url=None):
    """Convert a SQLAlchemy URL into a libpq connection string for psycopg.

    :param url: URL to convert, defaulting to :func:`database_url`.
    :returns: a libpq conninfo string such as ``host=... dbname=...``.
    """
    parts = urlsplit(normalize_url(url or database_url()))
    fields = {
        "host": parts.hostname or DEFAULTS["DB_HOST"],
        "port": parts.port or int(DEFAULTS["DB_PORT"]),
        "dbname": parts.path.lstrip("/") or DEFAULTS["DB_NAME"],
        "user": parts.username or DEFAULTS["DB_USER"],
    }
    if parts.password:
        fields["password"] = parts.password
    return " ".join(f"{key}={value}" for key, value in fields.items())


def database_name(url=None):
    """Return just the database name from *url*.

    :param url: URL to inspect, defaulting to :func:`database_url`.
    :returns: the database name.
    """
    parts = urlsplit(normalize_url(url or database_url()))
    return parts.path.lstrip("/") or DEFAULTS["DB_NAME"]


def url_for_database(name, url=None):
    """Return *url* pointed at a different database *name*.

    Used to reach the maintenance ``postgres`` database when the application
    database still has to be created.

    :param name: database to switch to.
    :param url: URL to rewrite, defaulting to :func:`database_url`.
    :returns: the rewritten URL.
    """
    base = normalize_url(url or database_url())
    head, _, _ = base.rpartition("/")
    return f"{head}/{name}"
