"""
Module 3 - query_data.py

Answers the assignment's analysis questions with raw SQL executed through
psycopg. All of the analysis is expressed in SQL; Python only runs the
statements and formats the output.

Usage:
    python query_data.py                 # run all 11 questions
    python query_data.py --question 8    # run one question
    python query_data.py "SELECT ..."    # run an ad-hoc query
    echo "SELECT ..." | python query_data.py -

Or from other code:
    from query_data import run_query, QUESTIONS
    columns, rows = run_query(QUESTIONS[0].sql)
"""

import os
import sys
from dataclasses import dataclass

import psycopg
from dotenv import load_dotenv  # This is for loading the environment variables for the database

from formatting import format_value

load_dotenv()  # Loads all those env variables

DB_NAME = os.getenv("DB_NAME", "module_3")


# ---------------------------------------------------------------- questions
@dataclass(frozen=True)
class Question:
    number: int
    title: str
    sql: str
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

QUESTIONS = [
    Question(
        1,
        "How many entries in the database are from applicants who applied for Fall 2026?",
        f"""
SELECT COUNT(*) AS "Fall 2026 applicant count"
FROM applicants
WHERE {FALL_2026};
""",
        "Counts every row whose term field is 'Fall 2026'. TRIM and LOWER make the "
        "comparison robust to stray whitespace and capitalization differences.",
    ),
    Question(
        2,
        "Among entries that provide a nationality classification, what percentage are international students?",
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
        "What are the average GPA, GRE Quantitative, GRE Verbal, and GRE Analytical Writing scores of applicants who provide each metric?",
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
        "How many entries are from applicants who applied to Johns Hopkins University for a master's degree in Computer Science?",
        f"""
SELECT COUNT(*) AS "JHU Computer Science master's entries"
FROM applicants
WHERE (program ILIKE '%johns hopkins%' OR program ~* '\\mjhu\\M')
  AND {CS_ORIGINAL}
  AND {MASTERS};
""",
        "Uses the original program and degree fields. The program text holds both the "
        "department and the university, so ILIKE matches 'Johns Hopkins' anywhere in it, "
        "and the \\m...\\M regex matches 'JHU' as a whole word. 'Computer Science' is "
        "matched as a substring, and the degree must be a master's variant (Masters, MS, "
        "M.S., MSc).",
    ),
    Question(
        8,
        "How many Fall 2026 entries are acceptances from applicants applying for a PhD in Computer Science at Georgetown, MIT, Stanford, or Carnegie Mellon (original fields)?",
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
        "degree (PhD / Ph.D.), 'Computer Science' somewhere in the original program "
        "text, and the original program text naming one of the four universities "
        "(full names plus the MIT / CMU abbreviations as whole words).",
    ),
    Question(
        9,
        "Repeat Question 8 using llm_generated_program and llm_generated_university for the program and university, and report both counts and their difference.",
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
        "matching, while 'llm' matches the LLM-standardized program with ILIKE and the "
        "LLM-standardized university with exact (case-insensitive) names. The final "
        "SELECT reports both counts side by side and their signed difference.",
    ),
    Question(
        10,
        "Original question 1: For Fall 2026, do American and international applicants report different acceptance rates?",
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
        "ratio into a percentage. Comparing the rows shows whether the two populations "
        "report different acceptance rates on Grad Cafe.",
    ),
    Question(
        11,
        "Original question 2: Which ten universities have the most Fall 2026 entries, and what are their acceptance percentages and average reported GPAs?",
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
        "into one group. Groups the Fall 2026 rows by university, orders the groups by "
        "size and keeps the ten largest, reporting each group's entry count, acceptance "
        "percentage and the average GPA among entries that report one.",
    ),
]


# ---------------------------------------------------------------- database
def conninfo(dbname=None):
    """
    Nice little function that returns the connection info in the psycopg object that it requires.
    All of these values are stored in an environment file called .env and gitignored.
    """
    return psycopg.conninfo.make_conninfo(
        dbname=dbname or DB_NAME,
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
    )


def execute_query(connection, query, params=None):
    """
    Executes a query string on an open connection.
    Returns (columns, rows) for queries that return data (SELECT, ... RETURNING),
    or (None, rowcount) for statements that don't (INSERT, UPDATE, DDL).
    """
    with connection.cursor() as cur:
        cur.execute(query, params)
        if cur.description is None:
            connection.commit()
            return None, cur.rowcount
        columns = [col.name for col in cur.description]
        return columns, cur.fetchall()


def run_query(query, params=None):
    """Opens a connection, runs the query, and returns the results."""
    with psycopg.connect(conninfo()) as conn:
        return execute_query(conn, query, params)


# ---------------------------------------------------------------- output
def format_results(columns, rows):
    """
    Returns the lines that print_results would print. Single-row results
    become 'Label: value' lines; multi-row results become an aligned table.
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


def print_results(columns, rows):
    print("\n".join(format_results(columns, rows)))


def run_question(question):
    """Runs one Question and returns (columns, rows)."""
    return run_query(question.sql)


def run_all(questions=QUESTIONS):
    """Runs every question and prints the formatted answers."""
    print("Module 3 - Raw SQL analysis (psycopg)")
    print(f"Database: {DB_NAME}\n")
    for q in questions:
        print(f"Question {q.number}: {q.title}")
        columns, rows = run_question(q)
        print_results(columns, rows)
        print()


# ---------------------------------------------------------------- cli
def main():
    args = sys.argv[1:]

    query = None
    selected = QUESTIONS

    if args and args[0] == "--question":
        wanted = {int(n) for n in args[1:]}
        selected = [q for q in QUESTIONS if q.number in wanted]
        if not selected:
            print(f"No question numbered {sorted(wanted)}; choose 1-{len(QUESTIONS)}")
            return 1
    elif args == ["-"]:
        query = sys.stdin.read().strip()  # piped query: echo "SELECT ..." | python query_data.py -
    elif args:
        query = " ".join(args)

    try:
        if query:
            columns, rows = run_query(query)
            print_results(columns, rows)
        else:
            run_all(selected)
    except psycopg.OperationalError as exc:
        print(f"Could not connect to PostgreSQL: {exc}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"The error '{exc}' occurred", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
