"""
Module 3 - models.py

SQLAlchemy 2.x ORM mapping for the existing `applicants` table that
load_data.py creates and fills. The engine and session factory point at the
same PostgreSQL database, using the same environment variables, so there is
exactly one copy of the data.

Usage:
    from models import Applicant, SessionLocal

    with SessionLocal() as session:
        total = session.scalar(select(func.count()).select_from(Applicant))
"""

import os
from datetime import date
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import URL, Date, Float, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

load_dotenv()

DATABASE_URL = URL.create(
    drivername="postgresql+psycopg",
    username=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD") or None,
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    database=os.getenv("DB_NAME", "module_3"),
)

# pool_pre_ping drops stale connections instead of raising mid-request in Flask.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# One session per unit of work: `with SessionLocal() as session:`
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Applicant(Base):
    """One Grad Cafe submission. Column names match load_data.py exactly."""

    __tablename__ = "applicants"

    p_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program: Mapped[Optional[str]] = mapped_column(Text)
    comments: Mapped[Optional[str]] = mapped_column(Text)
    date_added: Mapped[Optional[date]] = mapped_column(Date)
    url: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[Optional[str]] = mapped_column(Text)
    term: Mapped[Optional[str]] = mapped_column(Text)
    us_or_international: Mapped[Optional[str]] = mapped_column(Text)
    gpa: Mapped[Optional[float]] = mapped_column(Float)
    gre: Mapped[Optional[float]] = mapped_column(Float)
    gre_v: Mapped[Optional[float]] = mapped_column(Float)
    gre_aw: Mapped[Optional[float]] = mapped_column(Float)
    degree: Mapped[Optional[str]] = mapped_column(Text)
    llm_generated_program: Mapped[Optional[str]] = mapped_column(Text)
    llm_generated_university: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return f"Applicant(p_id={self.p_id!r}, program={self.program!r}, status={self.status!r})"


def get_session():
    """Convenience wrapper so callers don't import SessionLocal directly."""
    return SessionLocal()
