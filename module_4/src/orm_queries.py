"""The same eleven analysis questions, expressed with the SQLAlchemy ORM.

Only ``select()``, ``where()``, ``func``, ``and_()``, ``or_()`` and ORM
sessions are used; there is no ``text()`` and no psycopg cursor anywhere in
this module. The Flask page reads its numbers from :func:`analysis_results`,
so every value the browser shows has been through the ORM.

Run it from the command line::

    python -m src.orm_queries              # every question
    python -m src.orm_queries --required   # only 1, 4, 5, 8, 9 and one original
"""

import sys

from sqlalchemy import and_, func, or_, select

from . import config
from .formatting import fmt_avg, fmt_count, fmt_pct, fmt_signed
from .models import Applicant, get_session

#: Question numbers the assignment requires the ORM to reproduce.
REQUIRED = (1, 4, 5, 8, 9, 10)

# Reusable filter expressions; all text matching is case-insensitive.
FALL_2026 = func.lower(func.trim(Applicant.term)) == "fall 2026"
FALL_2025 = func.lower(func.trim(Applicant.term)) == "fall 2025"
ACCEPTED = Applicant.status.ilike("accept%")
PHD = Applicant.degree.regexp_match(r"ph\.?\s?d", flags="i")
MASTERS = or_(
    Applicant.degree.ilike("%master%"),
    Applicant.degree.regexp_match(r"^m\.?s(c|\.)?$", flags="i"),
)
HAS_NATIONALITY = and_(
    Applicant.us_or_international.is_not(None),
    func.trim(Applicant.us_or_international) != "",
)
CS_ORIGINAL = Applicant.program.ilike("%computer science%")
CS_LLM = Applicant.llm_generated_program.ilike("%computer science%")
TARGET_UNIS_ORIGINAL = or_(
    Applicant.program.ilike("%georgetown%"),
    Applicant.program.ilike("%massachusetts institute of technology%"),
    Applicant.program.regexp_match(r"\mmit\M", flags="i"),
    Applicant.program.ilike("%stanford%"),
    Applicant.program.ilike("%carnegie mellon%"),
    Applicant.program.regexp_match(r"\mcmu\M", flags="i"),
)
TARGET_UNIS_LLM = func.lower(func.trim(Applicant.llm_generated_university)).in_(
    [
        "georgetown university",
        "massachusetts institute of technology",
        "stanford university",
        "carnegie mellon university",
    ]
)


def _count(session, *conditions):
    """Run ``SELECT COUNT(*) FROM applicants WHERE ...``.

    :param session: an open ORM session.
    :param conditions: SQLAlchemy filter expressions.
    :returns: the count as an integer.
    """
    return session.scalar(select(func.count()).select_from(Applicant).where(*conditions)) or 0


def _percent(numerator, denominator):
    """Return ``numerator / denominator`` as a percentage.

    :param numerator: the count of interest.
    :param denominator: the total.
    :returns: the percentage, or ``None`` when the denominator is zero.
    """
    return None if not denominator else 100.0 * numerator / denominator


def q1_fall_2026_count(session):
    """Question 1: entries whose term is Fall 2026."""
    return _count(session, FALL_2026)


def q2_percent_international(session):
    """Question 2: percent international among rows with a usable nationality."""
    stmt = select(
        func.count(),
        func.count().filter(
            func.lower(func.trim(Applicant.us_or_international)) == "international"
        ),
    ).where(HAS_NATIONALITY)
    total, international = session.execute(stmt).one()
    return _percent(international, total)


def q3_averages(session):
    """Question 3: average GPA, GRE Q, GRE V and GRE AW, each over its own rows."""
    stmt = select(
        func.avg(Applicant.gpa),
        func.avg(Applicant.gre),
        func.avg(Applicant.gre_v),
        func.avg(Applicant.gre_aw),
    )
    return session.execute(stmt).one()


def q4_avg_gpa_american_fall_2026(session):
    """Question 4: average GPA of American Fall 2026 applicants reporting a GPA."""
    stmt = select(func.avg(Applicant.gpa)).where(
        FALL_2026,
        func.lower(func.trim(Applicant.us_or_international)) == "american",
        Applicant.gpa.is_not(None),
    )
    return session.scalar(stmt)


def q5_fall_2025_acceptance_percent(session):
    """Question 5: percentage of Fall 2025 entries that are acceptances."""
    stmt = select(func.count(), func.count().filter(ACCEPTED)).where(FALL_2025)
    total, accepted = session.execute(stmt).one()
    return _percent(accepted, total)


def q6_avg_gpa_accepted_fall_2026(session):
    """Question 6: average GPA of accepted Fall 2026 applicants reporting a GPA."""
    stmt = select(func.avg(Applicant.gpa)).where(
        FALL_2026, ACCEPTED, Applicant.gpa.is_not(None)
    )
    return session.scalar(stmt)


def q7_jhu_cs_masters_count(session):
    """Question 7: JHU Computer Science master's entries, original fields."""
    return _count(
        session,
        or_(
            Applicant.program.ilike("%johns hopkins%"),
            Applicant.program.regexp_match(r"\mjhu\M", flags="i"),
        ),
        CS_ORIGINAL,
        MASTERS,
    )


def q8_cs_phd_acceptances_original(session):
    """Question 8: Fall 2026 accepted CS PhD entries at the four target schools."""
    return _count(session, FALL_2026, ACCEPTED, PHD, CS_ORIGINAL, TARGET_UNIS_ORIGINAL)


def q9_cs_phd_acceptances_llm(session):
    """Question 9: Question 8 matched on the LLM-generated fields instead."""
    return _count(session, FALL_2026, ACCEPTED, PHD, CS_LLM, TARGET_UNIS_LLM)


def q10_acceptance_by_nationality(session):
    """Original question 1: Fall 2026 acceptance rate by nationality."""
    accepted = func.count().filter(ACCEPTED)
    stmt = (
        select(
            Applicant.us_or_international,
            func.count(),
            accepted,
            100.0 * accepted / func.count(),
        )
        .where(FALL_2026, HAS_NATIONALITY)
        .group_by(Applicant.us_or_international)
        .order_by(func.count().desc())
    )
    return session.execute(stmt).all()


def q11_top_universities(session, limit=10):
    """Original question 2: the universities with the most Fall 2026 entries.

    :param session: an open ORM session.
    :param limit: how many universities to return.
    :returns: rows of ``(university, entries, acceptance percent, average GPA)``.
    """
    accepted = func.count().filter(ACCEPTED)
    stmt = (
        select(
            Applicant.llm_generated_university,
            func.count(),
            100.0 * accepted / func.count(),
            func.avg(Applicant.gpa),
        )
        .where(FALL_2026, Applicant.llm_generated_university.is_not(None))
        .group_by(Applicant.llm_generated_university)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return session.execute(stmt).all()


def collect_results(session, numbers=None):
    """Run the questions and return display-ready dictionaries.

    Each entry is either::

        {"number": 1, "title": ..., "kind": "lines",
         "lines": [(label, formatted_value), ...]}

    or::

        {"number": 10, "title": ..., "kind": "table",
         "columns": [...], "rows": [[formatted, ...], ...]}

    Values are already formatted per the assignment rules, so percentages
    always carry two decimal places.

    :param session: an open ORM session.
    :param numbers: optional iterable of question numbers to keep.
    :returns: a list of result dictionaries.
    """
    q8 = q8_cs_phd_acceptances_original(session)
    q9 = q9_cs_phd_acceptances_llm(session)
    gpa, gre, gre_v, gre_aw = q3_averages(session)

    results = [
        {
            "number": 1,
            "title": "How many entries are from applicants who applied for Fall 2026?",
            "kind": "lines",
            "lines": [("Fall 2026 applicant count", fmt_count(q1_fall_2026_count(session)))],
        },
        {
            "number": 2,
            "title": "Among entries with a nationality classification, what percentage "
                     "are international?",
            "kind": "lines",
            "lines": [("Percent international", fmt_pct(q2_percent_international(session)))],
        },
        {
            "number": 3,
            "title": "Average GPA and GRE scores of applicants who provide each metric",
            "kind": "lines",
            "lines": [
                ("Average GPA", fmt_avg(gpa)),
                ("Average GRE Quantitative", fmt_avg(gre)),
                ("Average GRE Verbal", fmt_avg(gre_v)),
                ("Average GRE Analytical Writing", fmt_avg(gre_aw)),
            ],
        },
        {
            "number": 4,
            "title": "Average GPA of American applicants who applied for Fall 2026",
            "kind": "lines",
            "lines": [
                ("Average GPA (American, Fall 2026)",
                 fmt_avg(q4_avg_gpa_american_fall_2026(session))),
            ],
        },
        {
            "number": 5,
            "title": "What percentage of Fall 2025 entries are acceptances?",
            "kind": "lines",
            "lines": [
                ("Fall 2025 acceptance percentage",
                 fmt_pct(q5_fall_2025_acceptance_percent(session))),
            ],
        },
        {
            "number": 6,
            "title": "Average GPA of accepted applicants who applied for Fall 2026",
            "kind": "lines",
            "lines": [
                ("Average GPA (accepted, Fall 2026)",
                 fmt_avg(q6_avg_gpa_accepted_fall_2026(session))),
            ],
        },
        {
            "number": 7,
            "title": "Entries for a Johns Hopkins University master's degree in "
                     "Computer Science",
            "kind": "lines",
            "lines": [
                ("JHU Computer Science master's entries",
                 fmt_count(q7_jhu_cs_masters_count(session))),
            ],
        },
        {
            "number": 8,
            "title": "Fall 2026 acceptances for a PhD in Computer Science at "
                     "Georgetown, MIT, Stanford or Carnegie Mellon (original fields)",
            "kind": "lines",
            "lines": [("Original-field count", fmt_count(q8))],
        },
        {
            "number": 9,
            "title": "Question 8 repeated with the LLM-generated program and "
                     "university fields",
            "kind": "lines",
            "lines": [
                ("Original-field count", fmt_count(q8)),
                ("LLM-field count", fmt_count(q9)),
                ("Difference", fmt_signed(q9 - q8)),
            ],
        },
        {
            "number": 10,
            "title": "Original question 1: For Fall 2026, do American and "
                     "international applicants report different acceptance rates?",
            "kind": "table",
            "columns": ["Nationality", "Entries", "Accepted", "Acceptance percent"],
            "rows": [
                [nat, fmt_count(n), fmt_count(acc), fmt_pct(pct)]
                for nat, n, acc, pct in q10_acceptance_by_nationality(session)
            ],
        },
        {
            "number": 11,
            "title": "Original question 2: Which ten universities have the most Fall "
                     "2026 entries, and what are their acceptance percentages and "
                     "average reported GPAs?",
            "kind": "table",
            "columns": ["University", "Entries", "Acceptance percent", "Average GPA"],
            "rows": [
                [uni, fmt_count(n), fmt_pct(pct), fmt_avg(avg_gpa)]
                for uni, n, pct, avg_gpa in q11_top_universities(session)
            ],
        },
    ]
    if numbers:
        results = [r for r in results if r["number"] in numbers]
    return results


def analysis_results(numbers=None, session=None):
    """Return :func:`collect_results` using a session of its own.

    This is the default analysis provider injected into the Flask app.

    :param numbers: optional iterable of question numbers to keep.
    :param session: an existing session to reuse instead of opening one.
    :returns: a list of result dictionaries.
    """
    if session is not None:
        return collect_results(session, numbers)
    with get_session() as owned:
        return collect_results(owned, numbers)


def format_result(result):
    """Render one :func:`collect_results` entry as console text.

    :param result: a single result dictionary.
    :returns: the rendered string.
    """
    lines = [f"Question {result['number']}: {result['title']}"]
    if result["kind"] == "lines":
        lines.extend(f"{label}: {value}" for label, value in result["lines"])
    else:
        columns = result["columns"]
        rows = result["rows"]
        widths = [max([len(c)] + [len(r[i]) for r in rows]) for i, c in enumerate(columns)]
        lines.append(" | ".join(c.ljust(w) for c, w in zip(columns, widths)))
        lines.append("-+-".join("-" * w for w in widths))
        lines.extend(" | ".join(v.ljust(w) for v, w in zip(r, widths)) for r in rows)
        lines.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return "\n".join(lines)


def main(argv=None):
    """Command line entry point.

    :param argv: argument list, defaulting to :data:`sys.argv` minus the
        program name. ``--required`` limits output to :data:`REQUIRED`.
    :returns: a process exit code.
    """
    config.load_environment()
    argv = list(sys.argv[1:] if argv is None else argv)
    numbers = REQUIRED if "--required" in argv else None

    print("Module 4 - SQLAlchemy ORM analysis")
    for result in analysis_results(numbers):
        print()
        print(format_result(result))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
