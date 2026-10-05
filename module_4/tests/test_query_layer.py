"""The raw SQL and ORM analysis layers, and their command line entry points."""

import psycopg
import pytest

from src import load_data, orm_queries, query_data
from src.models import get_session

pytestmark = pytest.mark.analysis

#: A small, fully controlled dataset with known answers.
SEED = [
    # Fall 2026, American, accepted, CS PhD at Stanford, GPA 4.0
    {"entry_id": 1, "program": "Computer Science, Stanford University", "degree": "PhD",
     "applicant_status": "Accepted", "term": "Fall 2026", "applicant_type": "American",
     "gpa": 4.0, "gre_quant": 170, "gre_verbal": 160, "gre_aw": 5.0,
     "date_added": "2026-09-01", "url": "https://www.thegradcafe.com/result/1",
     "llm-generated-program": "Computer Science",
     "llm-generated-university": "Stanford University"},
    # Fall 2026, International, rejected, CS PhD at MIT, GPA 3.0
    {"entry_id": 2, "program": "Computer Science, Massachusetts Institute of Technology (MIT)",
     "degree": "PhD", "applicant_status": "Rejected", "term": "Fall 2026",
     "applicant_type": "International", "gpa": 3.0,
     "date_added": "2026-09-02", "url": "https://www.thegradcafe.com/result/2",
     "llm-generated-program": "Computer Science",
     "llm-generated-university": "Massachusetts Institute of Technology"},
    # Fall 2025, American, accepted, JHU CS master's
    {"entry_id": 3, "program": "Computer Science, Johns Hopkins University",
     "degree": "Masters", "applicant_status": "Accepted", "term": "Fall 2025",
     "applicant_type": "American", "gpa": 3.5,
     "date_added": "2025-09-03", "url": "https://www.thegradcafe.com/result/3",
     "llm-generated-program": "Computer Science",
     "llm-generated-university": "Johns Hopkins University"},
    # Fall 2025, no nationality at all, rejected
    {"entry_id": 4, "program": "History, Yale University", "degree": "PhD",
     "applicant_status": "Rejected", "term": "Fall 2025", "applicant_type": None,
     "date_added": "2025-09-04", "url": "https://www.thegradcafe.com/result/4",
     "llm-generated-program": "History", "llm-generated-university": "Yale University"},
]


@pytest.fixture
def seeded(db, database_url):
    """Load :data:`SEED` into the empty test table."""
    load_data.load_records(SEED, url=database_url)
    return database_url


# ------------------------------------------------------------- raw SQL
def test_questions_are_numbered_one_to_eleven():
    """All eleven analysis questions are present and in order."""
    assert [q.number for q in query_data.QUESTIONS] == list(range(1, 12))
    assert all(q.title and q.sql.strip() and q.explanation for q in query_data.QUESTIONS)


def test_every_question_runs_against_the_schema(seeded):
    """Each question executes and returns at least one column."""
    for question in query_data.QUESTIONS:
        columns, rows = query_data.run_question(question, url=seeded)
        assert columns, question.number
        assert rows is not None, question.number


@pytest.mark.parametrize(
    ("number", "expected"),
    [
        (1, 2),      # two Fall 2026 entries
        (7, 1),      # one JHU CS master's
        (8, 1),      # one accepted CS PhD at a target school
    ],
)
def test_count_questions_return_the_expected_counts(seeded, number, expected):
    """The counting questions agree with the seeded data."""
    question = next(q for q in query_data.QUESTIONS if q.number == number)
    _, rows = query_data.run_question(question, url=seeded)
    assert rows[0][0] == expected


def test_question_9_reports_both_counts_and_the_difference(seeded):
    """Question 9 puts the original and LLM counts side by side."""
    question = next(q for q in query_data.QUESTIONS if q.number == 9)
    columns, rows = query_data.run_question(question, url=seeded)
    assert columns == ["Original-field count", "LLM-field count", "Difference"]
    original, llm, difference = rows[0]
    assert difference == llm - original


def test_percentage_questions_round_to_two_decimals(seeded):
    """SQL rounds percentages before they ever reach Python."""
    question = next(q for q in query_data.QUESTIONS if q.number == 2)
    _, rows = query_data.run_question(question, url=seeded)
    # One international of three rows carrying a nationality.
    assert float(rows[0][0]) == pytest.approx(33.33)


def test_run_query_executes_an_ad_hoc_statement(seeded):
    """Arbitrary SQL runs through the same helper."""
    columns, rows = query_data.run_query("SELECT COUNT(*) AS n FROM applicants", url=seeded)
    assert columns == ["n"]
    assert rows[0][0] == 4


def test_execute_query_returns_a_rowcount_for_non_selects(seeded):
    """A statement that returns no rows reports how many it touched."""
    with query_data.connect(seeded) as conn:
        columns, affected = query_data.execute_query(
            conn, "UPDATE applicants SET comments = 'x' WHERE p_id = 1"
        )
    assert columns is None
    assert affected == 1


def test_analysis_summary_returns_the_expected_keys(seeded):
    """The summary dict carries exactly the keys the template expects."""
    summary = query_data.analysis_summary(url=seeded)
    assert set(summary) == {
        "total_entries", "fall_2026_count", "percent_international",
        "average_gpa", "average_gre", "average_gre_v", "average_gre_aw",
        "fall_2025_acceptance_percent",
    }
    assert summary["total_entries"] == "4"
    assert summary["fall_2026_count"] == "2"
    assert summary["percent_international"].endswith("%")
    assert summary["average_gpa"] == "3.50"


def test_analysis_summary_on_an_empty_table_is_all_na(db, database_url):
    """With no rows the averages and percentages render as N/A."""
    summary = query_data.analysis_summary(url=database_url)
    assert summary["total_entries"] == "0"
    assert summary["average_gpa"] == "N/A"
    assert summary["percent_international"] == "N/A"


# -------------------------------------------------------- console rendering
def test_format_results_renders_a_single_row_as_labelled_lines():
    """One row becomes ``Label: value`` lines."""
    lines = query_data.format_results(["Percent international"], [(50.0851,)])
    assert lines == ["Percent international: 50.09%"]


def test_format_results_renders_multiple_rows_as_a_table():
    """Several rows become an aligned table with a row count."""
    lines = query_data.format_results(
        ["University", "Entries"], [("Stanford University", 770), ("Yale University", 633)]
    )
    assert lines[0].startswith("University")
    assert "-+-" in lines[1]
    assert lines[-1] == "(2 rows)"


def test_format_results_reports_affected_rows_for_non_selects():
    """A non-returning statement reports its row count."""
    assert query_data.format_results(None, 3) == [
        "Query executed successfully (3 rows affected)"
    ]


def test_print_results_writes_to_the_given_stream():
    """Printing is redirectable, which keeps the CLI testable."""
    import io

    buffer = io.StringIO()
    query_data.print_results(["Entries"], [(5,)], stream=buffer)
    assert buffer.getvalue().strip() == "Entries: 5"


def test_run_all_prints_every_question(seeded, capsys):
    """``run_all`` prints a heading per question."""
    query_data.run_all(url=seeded)
    output = capsys.readouterr().out
    for question in query_data.QUESTIONS:
        assert f"Question {question.number}:" in output


# ----------------------------------------------------- raw SQL entry point
def test_query_data_main_runs_every_question(seeded, capsys):
    """``python -m src.query_data`` with no arguments answers all eleven."""
    assert query_data.main([]) == 0
    assert "Question 11:" in capsys.readouterr().out


def test_query_data_main_runs_one_question(seeded, capsys):
    """``--question 5`` answers only that one."""
    assert query_data.main(["--question", "5"]) == 0
    output = capsys.readouterr().out
    assert "Question 5:" in output
    assert "Question 1:" not in output


def test_query_data_main_rejects_an_unknown_question(seeded, capsys):
    """An out-of-range question number is an error, not a silent no-op."""
    assert query_data.main(["--question", "99"]) == 1
    assert "No question numbered" in capsys.readouterr().out


def test_query_data_main_runs_an_ad_hoc_query(seeded, capsys):
    """A bare SQL argument is executed directly."""
    assert query_data.main(["SELECT COUNT(*) AS n FROM applicants"]) == 0
    assert "n: 4" in capsys.readouterr().out


def test_query_data_main_reads_a_piped_query(seeded, capsys, monkeypatch):
    """A single ``-`` argument reads the query from standard input."""
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("SELECT COUNT(*) AS piped FROM applicants"))
    assert query_data.main(["-"]) == 0
    assert "piped: 4" in capsys.readouterr().out


def test_query_data_main_reports_a_connection_failure(monkeypatch, capsys):
    """An unreachable database is reported, not raised."""
    def boom(*args, **kwargs):
        raise psycopg.OperationalError("could not connect")

    monkeypatch.setattr(query_data, "connect", boom)
    assert query_data.main([]) == 1
    assert "Could not connect to PostgreSQL" in capsys.readouterr().err


def test_query_data_main_reports_a_sql_error(seeded, capsys):
    """Bad SQL is reported with its message."""
    assert query_data.main(["SELECT * FROM table_that_does_not_exist"]) == 1
    assert "occurred" in capsys.readouterr().err


# ------------------------------------------------------------------- ORM
def test_orm_and_sql_agree_on_every_shared_question(seeded):
    """The ORM reproduces the raw SQL answers exactly."""
    with get_session(seeded) as session:
        assert orm_queries.q1_fall_2026_count(session) == 2
        assert orm_queries.q7_jhu_cs_masters_count(session) == 1
        assert orm_queries.q8_cs_phd_acceptances_original(session) == 1
        assert orm_queries.q9_cs_phd_acceptances_llm(session) == 1
        assert orm_queries.q4_avg_gpa_american_fall_2026(session) == pytest.approx(4.0)
        assert orm_queries.q5_fall_2025_acceptance_percent(session) == pytest.approx(50.0)
        assert orm_queries.q6_avg_gpa_accepted_fall_2026(session) == pytest.approx(4.0)
        assert orm_queries.q2_percent_international(session) == pytest.approx(33.333, rel=1e-3)


def test_orm_averages_skip_missing_metrics(seeded):
    """Each average covers only the rows that supply that metric."""
    with get_session(seeded) as session:
        gpa, gre, gre_v, gre_aw = orm_queries.q3_averages(session)
    assert float(gpa) == pytest.approx(3.5)      # three rows report a GPA
    assert float(gre) == pytest.approx(170.0)    # only one reports a GRE
    assert float(gre_v) == pytest.approx(160.0)
    assert float(gre_aw) == pytest.approx(5.0)


def test_orm_percent_is_none_on_an_empty_table(db, database_url):
    """A zero denominator yields ``None`` rather than a division error."""
    with get_session(database_url) as session:
        assert orm_queries.q2_percent_international(session) is None
        assert orm_queries.q5_fall_2025_acceptance_percent(session) is None


def test_orm_grouped_questions_return_rows(seeded):
    """The two original questions group and order as expected."""
    with get_session(seeded) as session:
        by_nationality = orm_queries.q10_acceptance_by_nationality(session)
        universities = orm_queries.q11_top_universities(session, limit=2)

    assert {row[0] for row in by_nationality} == {"American", "International"}
    assert len(universities) == 2


def test_collect_results_formats_every_question(seeded):
    """Collected results are display ready, with two-decimal percentages."""
    with get_session(seeded) as session:
        results = orm_queries.collect_results(session)

    assert [r["number"] for r in results] == list(range(1, 12))
    for result in results:
        if result["kind"] == "lines":
            for label, value in result["lines"]:
                assert isinstance(value, str)
                if value.endswith("%"):
                    assert value.split(".")[-1].rstrip("%").__len__() == 2


def test_collect_results_can_be_filtered(seeded):
    """Passing numbers keeps only those questions."""
    with get_session(seeded) as session:
        results = orm_queries.collect_results(session, numbers=(1, 5))
    assert [r["number"] for r in results] == [1, 5]


def test_analysis_results_opens_its_own_session(seeded):
    """Called with no session, the helper manages one itself."""
    results = orm_queries.analysis_results()
    assert [r["number"] for r in results] == list(range(1, 12))


def test_analysis_results_reuses_a_given_session(seeded):
    """An existing session is used rather than a new one."""
    with get_session(seeded) as session:
        results = orm_queries.analysis_results(numbers=(1,), session=session)
    assert [r["number"] for r in results] == [1]


def test_format_result_renders_lines_and_tables(seeded):
    """Console rendering handles both result shapes."""
    with get_session(seeded) as session:
        results = orm_queries.collect_results(session)

    lines_block = orm_queries.format_result(next(r for r in results if r["kind"] == "lines"))
    table_block = orm_queries.format_result(next(r for r in results if r["kind"] == "table"))

    assert "Question 1:" in lines_block
    assert "-+-" in table_block
    assert table_block.rstrip().endswith("row)") or table_block.rstrip().endswith("rows)")


def test_required_questions_are_the_assignment_subset():
    """The ORM reproduces exactly the questions the assignment lists."""
    assert orm_queries.REQUIRED == (1, 4, 5, 8, 9, 10)


def test_orm_main_prints_every_question(seeded, capsys):
    """``python -m src.orm_queries`` answers all eleven."""
    assert orm_queries.main([]) == 0
    assert "Question 11:" in capsys.readouterr().out


def test_orm_main_required_subset(seeded, capsys):
    """``--required`` limits the output to the assignment's subset."""
    assert orm_queries.main(["--required"]) == 0
    output = capsys.readouterr().out
    assert "Question 10:" in output
    assert "Question 11:" not in output
