"""SQLAlchemy 2.x mapping for the ``applicants`` table.

The model maps the table that :mod:`src.load_data` creates; there is exactly
one copy of the data and the ORM and the raw-SQL layer read the same rows.

The engine is created lazily so that a test can point ``DATABASE_URL`` at a
throwaway database and call :func:`reset_engine` before anything connects.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, Float, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from . import config

_engine = None
_session_factory = None


class Base(DeclarativeBase):
    """Declarative base for every mapped class in the project."""


class Applicant(Base):
    """One Grad Cafe submission.

    The column names and types match the Module 3 schema exactly; changing
    them would break the loader, the raw SQL and the saved analysis.
    """

    __tablename__ = "applicants"

    #: Grad Cafe entry id. Primary key, and the uniqueness key for upserts.
    p_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    #: Free text combining department and university.
    program: Mapped[Optional[str]] = mapped_column(Text)
    #: Applicant comments.
    comments: Mapped[Optional[str]] = mapped_column(Text)
    #: Date the entry appeared on Grad Cafe.
    date_added: Mapped[Optional[date]] = mapped_column(Date)
    #: Link to the Grad Cafe entry.
    url: Mapped[Optional[str]] = mapped_column(Text)
    #: Cleaned admission status (Accepted / Rejected / Wait listed / Interview).
    status: Mapped[Optional[str]] = mapped_column(Text)
    #: Intended start term, e.g. ``"Fall 2026"``.
    term: Mapped[Optional[str]] = mapped_column(Text)
    #: Nationality classification (American / International / Other).
    us_or_international: Mapped[Optional[str]] = mapped_column(Text)
    #: Grade point average on a 4.0 scale.
    gpa: Mapped[Optional[float]] = mapped_column(Float)
    #: GRE Quantitative score.
    gre: Mapped[Optional[float]] = mapped_column(Float)
    #: GRE Verbal score.
    gre_v: Mapped[Optional[float]] = mapped_column(Float)
    #: GRE Analytical Writing score.
    gre_aw: Mapped[Optional[float]] = mapped_column(Float)
    #: Degree type, e.g. ``"PhD"`` or ``"Masters"``.
    degree: Mapped[Optional[str]] = mapped_column(Text)
    #: Department/program name standardised by the LLM.
    llm_generated_program: Mapped[Optional[str]] = mapped_column(Text)
    #: University name standardised by the LLM.
    llm_generated_university: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self):
        """Return a short developer-facing representation."""
        return (
            f"Applicant(p_id={self.p_id!r}, program={self.program!r}, "
            f"status={self.status!r})"
        )

    def as_dict(self):
        """Return the row as a plain dict keyed by the Module 3 field names.

        :returns: a dict with one key per column of the required schema.
        """
        return {column.name: getattr(self, column.name) for column in self.__table__.columns}


def get_engine(url=None):
    """Return the shared :class:`~sqlalchemy.engine.Engine`, creating it once.

    :param url: an explicit URL, which also replaces any cached engine.
        Defaults to :func:`src.config.database_url`.
    :returns: the engine.
    """
    global _engine, _session_factory
    if _engine is None or url is not None:
        _engine = create_engine(url or config.database_url(), pool_pre_ping=True)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_factory(url=None):
    """Return the shared :class:`~sqlalchemy.orm.sessionmaker`.

    :param url: forwarded to :func:`get_engine`.
    :returns: the session factory.
    """
    get_engine(url)
    return _session_factory


def get_session(url=None):
    """Open a new ORM :class:`~sqlalchemy.orm.Session`.

    Intended to be used as a context manager::

        with get_session() as session:
            ...

    :param url: forwarded to :func:`get_engine`.
    :returns: a new session.
    """
    return get_session_factory(url)()


def reset_engine():
    """Dispose of the cached engine so the next call rebuilds it.

    Tests call this after changing ``DATABASE_URL``.
    """
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def create_all(url=None):
    """Create the ``applicants`` table when it does not exist yet.

    :param url: forwarded to :func:`get_engine`.
    """
    Base.metadata.create_all(get_engine(url))
