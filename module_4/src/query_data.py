"""Raw SQL analysis executed through psycopg.

The analysis itself lives in SQL; Python only runs the statements and formats
the answers. The same eleven questions are expressed with the ORM in
:mod:`src.orm_queries`, and the two modules must agree.

Run it from the command line::

    python -m src.query_data                 # all eleven questions
    python -m src.query_data --question 8    # one question
    python -m src.query_data "SELECT ..."    # an ad-hoc query
"""

import sys
from dataclasses import dataclass

import psycopg

from . import config
from .formatting import fmt_avg, fmt_count, fmt_pct, format_value

#: Column names of the required Module 3 schema, in table order.
REQUIRED_FIELDS = (
    "p_id", "program", "comments", "date_added", "url", "status", "term",
    "us_or_international", "gpa", "gre", "gre_v", "gre_aw", "degree",
    "llm_generated_program", "llm_generated_university",
)


@dataclass(frozen=True)
class Question:
    """One analysis question: its wording, its SQL and why the SQL answers it."""

    #: Position in the assignment's list, 1-11.
    number: int
    #: The question in ordinary English.
    title: str
    #: The executable SQL.
    sql: str
    #: Prose explaining what the query does.
    explanation: str


# Reusable predicate fragments. Text matching is case-insensitive throughout.
FALL_2026 = "LOWER(TRIM(term)) = 'fall 2026'"
FALL_2025 = "LOWER(TRIM(term)) = 'fall 2025'"
ACCEPTED = "status ILIKE 'accept%'"
PHD = "degree ~* 'ph\\.?\\s?d'"
MASTERS = "(degree ILIKE '%master%' OR degree ~* '^m\\.?s(c|\\.)?$')"
CS_ORIGINAL = "program ILIKE '%computer science%'"
CS_LLM = "llm_generated_program ILIKE '%computer science%'"
TARGET_UNIS_ORIGINAL = """(
         program ILIKE '%georgetown%'
      OR program ILIKE '%massachusetts institute of technology%'
      OR program ~* '\\mmit\\M'
      OR program ILIKE '%stanford%'
      OR program ILIKE '%carnegie mellon%'
      OR program ~* '\\mcmu\\M'
  )"""
TARGET_UNIS_LLM = """LOWER(TRIM(llm_generated_university)) IN (
         'georgetown university',
         'massachusetts institute of technology',
         'stanford university',
         'carnegie mellon university'
  )"""

#: The eleven analysis questions: 1-9 from the assignment plus two of my own.
QUESTIONS = [
    Question(
        1,
        "How many entries in the database are from applicants who applied for Fall 2026?",
        f'\nSELECT COUNT(*) AS "Fall 2026 applicant count"\nFROM applicants\nWHERE {FALL_2026};\n',
        "Counts every row whose term field is 'Fall 2026'. TRIM and LOWER make the "
        "comparison robust to stray whitespace and capitalization differences.",
    ),
    Question(
        2,
        "Among entries that provide a nationality classification, what percentage are "
        "international students?",
        """
SELECT ROUND(
         100.0 * COUNT(*) FILTER (WHERE LOWER(TRIM(us_or_international)) = 'international')
         / NULLIF(COUNT(*), 0),
       2) AS "Percent international"
FROM applicants
WHERE us_or_international IS NOT NULL
  AND TRIM(us_or_international) <> '';
""",
        "The WHERE clause restricts the denominator to rows with a usable nationality "
        "value (NULL and blank strings are excluded). The FILTER clause counts only the "
        "rows labelled 'International' for the numerator, so 'American' and 'Other' are "
        "in the denominator but not the numerator. NULLIF avoids division by zero.",
    ),
    Question(
        3,
        "What are the average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical "
        "Writing scores of applicants who provide each metric?",
        """
SELECT ROUND(AVG(gpa)::numeric, 2)    AS "Average GPA",
       ROUND(AVG(gre)::numeric, 2)    AS "Average GRE Quantitative",
       ROUND(AVG(gre_v)::numeric, 2)  AS "Average GRE Verbal",
       ROUND(AVG(gre_aw)::numeric, 2) AS "Average GRE Analytical Writing"
FROM applicants;
""",
        "AVG() ignores NULLs, so each column's average is computed only over the rows "
        "that supply that particular metric. An applicant with a GPA but no GRE still "
        "contributes to the GPA average, which is exactly what the assignment asks for.",
    ),
    Question(
        4,
        "What is the average GPA of American applicants who applied for Fall 2026?",
        f"""
SELECT ROUND(AVG(gpa)::numeric, 2) AS "Average GPA (American, Fall 2026)"
FROM applicants
WHERE {FALL_2026}
  AND LOWER(TRIM(us_or_international)) = 'american'
  AND gpa IS NOT NULL;
""",
        "Filters to Fall 2026 rows classified as American that also report a GPA, then "
        "averages that GPA. The explicit gpa IS NOT NULL mirrors the requirement even "
        "though AVG() would skip NULLs anyway.",
    ),
    Question(
        5,
        "What percentage of Fall 2025 entries are acceptances?",
        f"""
SELECT ROUND(
         100.0 * COUNT(*) FILTER (WHERE {ACCEPTED})
         / NULLIF(COUNT(*), 0),
       2) AS "Fall 2025 acceptance percentage"
FROM applicants
WHERE {FALL_2025};
""",
        "All Fall 2025 rows form the denominator; the FILTER clause counts the subset "
        "whose cleaned status starts with 'Accept' (the cleaned status values are "
        "Accepted / Rejected / Wait listed / Interview) for the numerator.",
    ),
    Question(
        6,
        "What is the average GPA of accepted applicants who applied for Fall 2026?",
        f"""
SELECT ROUND(AVG(gpa)::numeric, 2) AS "Average GPA (accepted, Fall 2026)"
FROM applicants
WHERE {FALL_2026}
  AND {ACCEPTED}
  AND gpa IS NOT NULL;
""",
        "Same shape as Question 4, but the nationality filter is replaced by an "
        "acceptance filter on the status column.",
    ),
    Question(
        7,
        "How many entries are from applicants who applied to Johns Hopkins University "
        "for a master's degree in Computer Science?",
        f"""
SELECT COUNT(*) AS "JHU Computer Science master's entries"
FROM applicants
WHERE (program ILIKE '%johns hopkins%' OR program ~* '\\mjhu\\M')
  AND {CS_ORIGINAL}
  AND {MASTERS};
""",
        "Uses the original program and degree fields. The program text holds both the "
        "department and the university, so ILIKE matches 'Johns Hopkins' anywhere in it, "
        "and the whole-word regex matches 'JHU'. The degree must be a master's variant "
        "(Masters, MS, M.S., MSc).",
    ),
    Question(
        8,
        "How many Fall 2026 entries are acceptances from applicants applying for a PhD "
        "in Computer Science at Georgetown, MIT, Stanford, or Carnegie Mellon "
        "(original fields)?",
        f"""
SELECT COUNT(*) AS "Original-field count"
FROM applicants
WHERE {FALL_2026}
  AND {ACCEPTED}
  AND {PHD}
  AND {CS_ORIGINAL}
  AND {TARGET_UNIS_ORIGINAL};
""",
        "All five restrictions are ANDed together: the term, an accepted status, a PhD "
        "degree, 'Computer Science' somewhere in the original program text, and the "
        "original program text naming one of the four universities.",
    ),
    Question(
        9,
        "Repeat Question 8 using llm_generated_program and llm_generated_university, "
        "and report both counts and their difference.",
        f"""
WITH base AS (
    SELECT program, llm_generated_program, llm_generated_university
    FROM applicants
    WHERE {FALL_2026}
      AND {ACCEPTED}
      AND {PHD}
),
original AS (
    SELECT COUNT(*) AS n FROM base
    WHERE {CS_ORIGINAL}
      AND {TARGET_UNIS_ORIGINAL}
),
llm AS (
    SELECT COUNT(*) AS n FROM base
    WHERE {CS_LLM}
      AND {TARGET_UNIS_LLM}
)
SELECT original.n          AS "Original-field count",
       llm.n               AS "LLM-field count",
       llm.n - original.n  AS "Difference"
FROM original, llm;
""",
        "The CTE 'base' applies the filters that stay on the original fields (term, "
        "status, degree). 'original' re-applies the Question 8 program/university "
        "matching, while 'llm' matches the LLM-standardized fields. The final SELECT "
        "reports both counts side by side and their signed difference.",
    ),
    Question(
        10,
        "Original question 1: For Fall 2026, do American and international applicants "
        "report different acceptance rates?",
        f"""
SELECT us_or_international AS "Nationality",
       COUNT(*) AS "Entries",
       COUNT(*) FILTER (WHERE {ACCEPTED}) AS "Accepted",
       ROUND(100.0 * COUNT(*) FILTER (WHERE {ACCEPTED}) / COUNT(*), 2) AS "Acceptance percent"
FROM applicants
WHERE {FALL_2026}
  AND us_or_international IS NOT NULL
  AND TRIM(us_or_international) <> ''
GROUP BY us_or_international
ORDER BY "Entries" DESC;
""",
        "Groups the Fall 2026 rows that carry a nationality label and, for each group, "
        "counts the entries, counts the acceptances with a FILTER clause, and turns the "
        "ratio into a percentage.",
    ),
    Question(
        11,
        "Original question 2: Which ten universities have the most Fall 2026 entries, "
        "and what are their acceptance percentages and average reported GPAs?",
        f"""
SELECT llm_generated_university AS "University",
       COUNT(*) AS "Entries",
       ROUND(100.0 * COUNT(*) FILTER (WHERE {ACCEPTED}) / COUNT(*), 2) AS "Acceptance percent",
       ROUND(AVG(gpa)::numeric, 2) AS "Average GPA"
FROM applicants
WHERE {FALL_2026}
  AND llm_generated_university IS NOT NULL
GROUP BY llm_generated_university
ORDER BY COUNT(*) DESC
LIMIT 10;
""",
        "Uses the LLM-standardized university name so that spelling variants collapse "
        "into one group, then keeps the ten largest groups.",
    ),
]


def connect(url=None):
    """Open a psycopg connection to the application database.

    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: an open :class:`psycopg.Connection`.
    """
    return psycopg.connect(config.psycopg_conninfo(url))


def execute_query(connection, query, params=None):
    """Execute *query* on an already-open connection.

    :param connection: an open psycopg connection.
    :param query: the SQL to run.
    :param params: optional query parameters.
    :returns: ``(columns, rows)`` for statements that return data, or
        ``(None, rowcount)`` for statements that do not.
    """
    with connection.cursor() as cur:
        cur.execute(query, params)
        if cur.description is None:
            connection.commit()
            return None, cur.rowcount
        columns = [col.name for col in cur.description]
        return columns, cur.fetchall()


def run_query(query, params=None, url=None):
    """Open a connection, run *query* and return the result.

    :param query: the SQL to run.
    :param params: optional query parameters.
    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: ``(columns, rows)`` as described in :func:`execute_query`.
    """
    with connect(url) as conn:
        return execute_query(conn, query, params)


def run_question(question, url=None):
    """Run one :class:`Question`.

    :param question: the question to run.
    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: ``(columns, rows)``.
    """
    return run_query(question.sql, url=url)


def fetch_applicant(p_id, url=None):
    """Return one applicant row as a dict keyed by :data:`REQUIRED_FIELDS`.

    This is the "simple query function" the analysis template relies on: the
    keys are exactly the required Module 3 fields.

    :param p_id: the Grad Cafe entry id.
    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: a dict with one key per required field, or ``None`` when the row
        does not exist.
    """
    columns = ", ".join(REQUIRED_FIELDS)
    _, rows = run_query(
        f"SELECT {columns} FROM applicants WHERE p_id = %s", (p_id,), url=url
    )
    if not rows:
        return None
    return dict(zip(REQUIRED_FIELDS, rows[0]))


def fetch_applicants(limit=100, url=None):
    """Return up to *limit* applicant rows as dicts.

    :param limit: maximum number of rows.
    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: a list of dicts keyed by :data:`REQUIRED_FIELDS`.
    """
    columns = ", ".join(REQUIRED_FIELDS)
    _, rows = run_query(
        f"SELECT {columns} FROM applicants ORDER BY p_id DESC LIMIT %s",
        (limit,),
        url=url,
    )
    return [dict(zip(REQUIRED_FIELDS, row)) for row in rows]


def analysis_summary(url=None):
    """Return the headline analysis numbers as a dict of formatted strings.

    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :returns: a dict with the keys ``total_entries``, ``fall_2026_count``,
        ``percent_international``, ``average_gpa``, ``average_gre``,
        ``average_gre_v``, ``average_gre_aw`` and
        ``fall_2025_acceptance_percent``.
    """
    _, rows = run_query(
        f"""
        SELECT COUNT(*),
               COUNT(*) FILTER (WHERE {FALL_2026}),
               100.0 * COUNT(*) FILTER (
                   WHERE LOWER(TRIM(us_or_international)) = 'international')
                   / NULLIF(COUNT(*) FILTER (
                       WHERE us_or_international IS NOT NULL
                         AND TRIM(us_or_international) <> ''), 0),
               AVG(gpa), AVG(gre), AVG(gre_v), AVG(gre_aw),
               100.0 * COUNT(*) FILTER (WHERE {FALL_2025} AND {ACCEPTED})
                   / NULLIF(COUNT(*) FILTER (WHERE {FALL_2025}), 0)
        FROM applicants
        """,
        url=url,
    )
    total, fall26, intl, gpa, gre, gre_v, gre_aw, acc25 = rows[0]
    return {
        "total_entries": fmt_count(total),
        "fall_2026_count": fmt_count(fall26),
        "percent_international": fmt_pct(intl),
        "average_gpa": fmt_avg(gpa),
        "average_gre": fmt_avg(gre),
        "average_gre_v": fmt_avg(gre_v),
        "average_gre_aw": fmt_avg(gre_aw),
        "fall_2025_acceptance_percent": fmt_pct(acc25),
    }


def format_results(columns, rows):
    """Render a query result as console lines.

    A single-row result becomes ``Label: value`` lines; a multi-row result
    becomes an aligned text table.

    :param columns: column names, or ``None`` for a non-returning statement.
    :param rows: the rows, or the affected row count when *columns* is ``None``.
    :returns: a list of strings.
    """
    if columns is None:
        return [f"Query executed successfully ({rows:,} rows affected)"]

    if len(rows) == 1:
        return [f"{col}: {format_value(col, val)}" for col, val in zip(columns, rows[0])]

    cells = [[format_value(col, v) for col, v in zip(columns, row)] for row in rows]
    widths = [
        max([len(col)] + [len(row[i]) for row in cells])
        for i, col in enumerate(columns)
    ]
    lines = [
        " | ".join(col.ljust(w) for col, w in zip(columns, widths)),
        "-+-".join("-" * w for w in widths),
    ]
    lines.extend(" | ".join(val.ljust(w) for val, w in zip(row, widths)) for row in cells)
    lines.append(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")
    return lines


def print_results(columns, rows, stream=None):
    """Print what :func:`format_results` renders.

    :param columns: column names, or ``None``.
    :param rows: the rows or affected row count.
    :param stream: file object to write to, defaulting to stdout.
    """
    print("\n".join(format_results(columns, rows)), file=stream)


def run_all(questions=None, url=None, stream=None):
    """Run every question and print the formatted answers.

    :param questions: questions to run, defaulting to :data:`QUESTIONS`.
    :param url: connection URL, defaulting to ``DATABASE_URL``.
    :param stream: file object to write to, defaulting to stdout.
    """
    questions = QUESTIONS if questions is None else questions
    print("Module 4 - Raw SQL analysis (psycopg)", file=stream)
    for question in questions:
        print(f"\nQuestion {question.number}: {question.title}", file=stream)
        columns, rows = run_question(question, url=url)
        print_results(columns, rows, stream=stream)


def main(argv=None):
    """Command line entry point.

    :param argv: argument list, defaulting to :data:`sys.argv` minus the
        program name.
    :returns: a process exit code.
    """
    config.load_environment()
    argv = list(sys.argv[1:] if argv is None else argv)

    query = None
    selected = QUESTIONS
    if argv and argv[0] == "--question":
        wanted = {int(n) for n in argv[1:]}
        selected = [q for q in QUESTIONS if q.number in wanted]
        if not selected:
            print(f"No question numbered {sorted(wanted)}; choose 1-{len(QUESTIONS)}")
            return 1
    elif argv == ["-"]:
        query = sys.stdin.read().strip()
    elif argv:
        query = " ".join(argv)

    try:
        if query:
            print_results(*run_query(query))
        else:
            run_all(selected)
    except psycopg.OperationalError as exc:
        print(f"Could not connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"The error '{exc}' occurred", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via main()
    raise SystemExit(main())
