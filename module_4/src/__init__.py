"""Grad Cafe analytics application (Module 4).

The package bundles the three layers of the service:

``config``, ``models``
    Database connection handling (PostgreSQL via ``DATABASE_URL``).

``browser``, ``scrape``, ``clean``, ``standardize``, ``load_data``, ``pull_data``
    The ETL layer: fetch Grad Cafe pages, normalise the rows and upsert them.

``query_data``, ``orm_queries``, ``formatting``, ``flask_app``
    The analysis and web layer.
"""

__all__ = [
    "browser",
    "clean",
    "config",
    "flask_app",
    "formatting",
    "load_data",
    "models",
    "orm_queries",
    "pull_data",
    "query_data",
    "scrape",
    "standardize",
]
