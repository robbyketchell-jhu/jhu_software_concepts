"""Labels and numeric formatting of the rendered analysis."""

import re

import pytest
from bs4 import BeautifulSoup

from src.formatting import (
    fmt_avg,
    fmt_count,
    fmt_pct,
    fmt_signed,
    format_value,
    is_percent,
)

pytestmark = pytest.mark.analysis

#: Any percentage appearing in rendered text.
ANY_PERCENT = re.compile(r"\d[\d,]*(?:\.\d+)?\s*%")
#: A percentage with exactly two decimal places.
TWO_DECIMAL_PERCENT = re.compile(r"^\d[\d,]*\.\d{2}\s*%$")


def page_text(client):
    """Return the visible text of the analysis page."""
    return BeautifulSoup(client.get("/analysis").data, "html.parser").get_text(" ")


# ------------------------------------------------------------ page labels
def test_rendered_answers_carry_an_answer_label(static_client):
    """Every analysis card is labelled with ``Answer:``."""
    soup = BeautifulSoup(static_client.get("/analysis").data, "html.parser")
    cards = soup.select("[data-testid^='result-']")

    assert cards
    for card in cards:
        assert "Answer:" in card.get_text(), card.get("data-testid")


def test_page_has_at_least_one_answer_label(static_client):
    """The page carries at least one ``Answer:`` label overall."""
    assert page_text(static_client).count("Answer:") >= 1


def test_every_answer_value_is_rendered(static_client):
    """Each answer value element holds non-empty text."""
    soup = BeautifulSoup(static_client.get("/analysis").data, "html.parser")
    values = soup.find_all(attrs={"data-testid": "answer-value"})

    assert values
    assert all(value.get_text(strip=True) for value in values)


# -------------------------------------------------------- page percentages
def test_every_percentage_on_the_page_has_two_decimals(static_client):
    """No percentage renders with varying precision."""
    found = ANY_PERCENT.findall(page_text(static_client))

    assert found, "expected the analysis page to show at least one percentage"
    for value in found:
        assert TWO_DECIMAL_PERCENT.match(value.strip()), value


def test_percentages_in_table_cells_have_two_decimals(static_client):
    """Percentages inside result tables follow the same rule."""
    soup = BeautifulSoup(static_client.get("/analysis").data, "html.parser")
    cells = [td.get_text(strip=True) for td in soup.select("table td")]
    percents = [c for c in cells if c.endswith("%")]

    assert percents
    assert all(TWO_DECIMAL_PERCENT.match(c) for c in percents), percents


def test_percentages_from_live_data_have_two_decimals(client, db, row_count):
    """The same rule holds for numbers computed from real database rows."""
    client.post("/pull-data")
    assert row_count() == 4

    found = ANY_PERCENT.findall(page_text(client))

    assert found
    assert all(TWO_DECIMAL_PERCENT.match(v.strip()) for v in found), found


# ----------------------------------------------------- formatting helpers
@pytest.mark.parametrize(
    ("value", "expected"),
    [(0, "0"), (1, "1"), (19290, "19,290"), (1234567, "1,234,567"), (None, "N/A")],
)
def test_fmt_count(value, expected):
    """Counts render as whole numbers with thousands separators."""
    assert fmt_count(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(50.09, "50.09%"), (39.2765, "39.28%"), (0, "0.00%"), (100, "100.00%"),
     (None, "N/A")],
)
def test_fmt_pct(value, expected):
    """Percentages always render with exactly two decimals."""
    assert fmt_pct(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [(3.7872697974217457, "3.79"), (164.87784679089026, "164.88"), (4, "4.00"),
     (None, "N/A")],
)
def test_fmt_avg(value, expected):
    """Averages always render with exactly two decimals."""
    assert fmt_avg(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"), [(3, "+3"), (-2, "-2"), (0, "+0"), (None, "N/A")]
)
def test_fmt_signed(value, expected):
    """Differences render with an explicit sign."""
    assert fmt_signed(value) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [("Percent international", True), ("Acceptance percent", True),
     ("Share %", True), ("pct_total", True), ("Average GPA", False),
     ("Entries", False)],
)
def test_is_percent(label, expected):
    """Percentage columns are recognised from their label."""
    assert is_percent(label) is expected


@pytest.mark.parametrize(
    ("label", "value", "expected"),
    [
        ("Entries", 19290, "19,290"),
        ("Difference", 3, "+3"),
        ("Difference", -1, "-1"),
        ("Percent international", 50.0851, "50.09%"),
        ("Average GPA", 3.786, "3.79"),
        ("University", "Stanford University", "Stanford University"),
        ("Average GPA", None, "N/A"),
        ("Flag", True, "True"),
    ],
)
def test_format_value_applies_the_rule_implied_by_the_label(label, value, expected):
    """``format_value`` picks the rule from the column label."""
    assert format_value(label, value) == expected


def test_format_value_handles_decimals():
    """``Decimal`` results from PostgreSQL format like floats."""
    from decimal import Decimal

    assert format_value("Average GPA", Decimal("3.7850")) == "3.79"
    assert format_value("Acceptance percent", Decimal("39.2765")) == "39.28%"
