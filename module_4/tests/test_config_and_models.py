"""Connection configuration and the SQLAlchemy mapping."""

import datetime

import pytest
from sqlalchemy import select

from src import config, models

pytestmark = pytest.mark.db


# ------------------------------------------------------------------ config
def test_database_url_prefers_the_environment(monkeypatch):
    """``DATABASE_URL`` wins over the individual variables."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://alice@db.example:6543/app")
    assert config.database_url() == "postgresql+psycopg://alice@db.example:6543/app"


def test_database_url_falls_back_to_the_parts(monkeypatch):
    """Without ``DATABASE_URL`` the ``DB_*`` variables are assembled."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_USER", "bob")
    monkeypatch.setenv("DB_PASSWORD", "")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "gradcafe")
    assert config.database_url() == "postgresql+psycopg://bob@localhost:5432/gradcafe"


def test_database_url_quotes_a_password(monkeypatch):
    """A password with reserved characters is percent-encoded."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_USER", "bob")
    monkeypatch.setenv("DB_PASSWORD", "p@ss word/1")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_PORT", "5432")
    monkeypatch.setenv("DB_NAME", "gradcafe")
    assert config.database_url() == (
        "postgresql+psycopg://bob:p%40ss%20word%2F1@localhost:5432/gradcafe"
    )


def test_database_url_uses_defaults(monkeypatch):
    """With nothing set at all, the documented defaults apply."""
    for name in ("DATABASE_URL", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    assert config.database_url() == "postgresql+psycopg://postgres@localhost:5432/gradcafe"


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgres://u@h:1/d", "postgresql+psycopg://u@h:1/d"),
        ("postgresql://u@h:1/d", "postgresql+psycopg://u@h:1/d"),
        ("postgresql+psycopg://u@h:1/d", "postgresql+psycopg://u@h:1/d"),
        ("sqlite:///file.db", "sqlite:///file.db"),
    ],
)
def test_normalize_url(given, expected):
    """Provider-style URLs are rewritten onto the psycopg driver."""
    assert config.normalize_url(given) == expected


def test_psycopg_conninfo_without_a_password():
    """A password-less URL yields a conninfo string with no password field."""
    info = config.psycopg_conninfo("postgresql://bob@localhost:5432/gradcafe")
    assert "host=localhost" in info
    assert "dbname=gradcafe" in info
    assert "user=bob" in info
    assert "password" not in info


def test_psycopg_conninfo_with_a_password():
    """A password in the URL reaches the conninfo string."""
    info = config.psycopg_conninfo("postgresql://bob:secret@localhost:5432/gradcafe")
    assert "password=secret" in info


def test_psycopg_conninfo_applies_defaults():
    """Missing URL parts fall back to the documented defaults."""
    info = config.psycopg_conninfo("postgresql+psycopg:///")
    assert "host=localhost" in info
    assert "port=5432" in info
    assert "dbname=gradcafe" in info
    assert "user=postgres" in info


def test_database_name():
    """The database name is read out of the URL."""
    assert config.database_name("postgresql://u@h:1/analytics") == "analytics"


def test_url_for_database_swaps_the_name():
    """Only the database segment changes when switching databases."""
    swapped = config.url_for_database("postgres", "postgresql://u@h:1/analytics")
    assert swapped == "postgresql+psycopg://u@h:1/postgres"


def test_load_environment_reads_a_dotenv_file(tmp_path, monkeypatch):
    """A ``.env`` file is loaded without overriding what is already set."""
    monkeypatch.delenv("GRADCAFE_SAMPLE", raising=False)
    env = tmp_path / ".env"
    env.write_text("GRADCAFE_SAMPLE=from-dotenv\n")

    assert config.load_environment(str(env)) is True

    import os

    assert os.environ["GRADCAFE_SAMPLE"] == "from-dotenv"
    monkeypatch.delenv("GRADCAFE_SAMPLE", raising=False)


# ------------------------------------------------------------------ models
def test_applicant_maps_the_required_table():
    """The model points at the table the loader creates."""
    assert models.Applicant.__tablename__ == "applicants"
    assert models.Applicant.__table__.primary_key.columns.keys() == ["p_id"]


def test_applicant_repr_is_readable():
    """``repr`` shows the identifying fields."""
    applicant = models.Applicant(p_id=7, program="Physics, MIT", status="Accepted")
    assert repr(applicant) == (
        "Applicant(p_id=7, program='Physics, MIT', status='Accepted')"
    )


def test_applicant_as_dict_covers_every_column():
    """``as_dict`` returns one key per column of the required schema."""
    applicant = models.Applicant(p_id=8, program="History, Yale")
    record = applicant.as_dict()
    assert set(record) == set(models.Applicant.__table__.columns.keys())
    assert record["p_id"] == 8
    assert record["gpa"] is None


def test_get_session_reads_rows_written_by_the_loader(db, database_url):
    """The ORM and the psycopg loader see the same table."""
    db.execute(
        "INSERT INTO applicants (p_id, program, status, term, date_added) "
        "VALUES (31, 'Physics, MIT', 'Accepted', 'Fall 2026', '2026-09-01')"
    )
    with models.get_session(database_url) as session:
        applicant = session.scalar(select(models.Applicant).where(models.Applicant.p_id == 31))

    assert applicant.program == "Physics, MIT"
    assert applicant.date_added == datetime.date(2026, 9, 1)


def test_get_engine_is_cached(database_url):
    """Repeated calls reuse one engine."""
    first = models.get_engine()
    assert models.get_engine() is first


def test_reset_engine_rebuilds_the_engine(database_url):
    """Resetting forces the next call to build a fresh engine."""
    first = models.get_engine(database_url)
    models.reset_engine()
    assert models.get_engine(database_url) is not first


def test_reset_engine_is_safe_when_nothing_was_built():
    """Resetting twice does not raise."""
    models.reset_engine()
    models.reset_engine()
    assert models._engine is None


def test_create_all_creates_the_table(database_url, db):
    """``create_all`` is a no-op once the table exists."""
    models.create_all(database_url)
    assert db.execute("SELECT to_regclass('applicants')").fetchone()[0] == "applicants"


def test_get_session_factory_returns_a_sessionmaker(database_url):
    """The factory is reusable and bound to the engine."""
    factory = models.get_session_factory(database_url)
    with factory() as session:
        assert session.bind is models.get_engine()
