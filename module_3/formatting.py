"""
Module 3 - formatting.py

One place for the assignment's output rules so the console scripts, the PDF
and the Flask page all agree:

    Counts       -> whole numbers with thousands separators   19,290
    Percentages  -> 2 decimal places plus %                   50.09%
    Averages     -> 2 decimal places                          3.79
    Differences  -> signed whole numbers                      +3
"""

from decimal import Decimal


def fmt_count(value):
    return "N/A" if value is None else f"{int(value):,}"


def fmt_pct(value):
    return "N/A" if value is None else f"{float(value):.2f}%"


def fmt_avg(value):
    return "N/A" if value is None else f"{float(value):.2f}"


def fmt_signed(value):
    return "N/A" if value is None else f"{int(value):+,}"


def is_percent(label):
    """A column is treated as a percentage if its name/alias mentions percent or %."""
    label = label.lower()
    return "percent" in label or "%" in label or label.startswith("pct")


def format_value(label, value):
    """
    Formats a value per the assignment's output rules using the column label
    (alias) to decide which rule applies. Percent columns are expected to
    already be on a 0-100 scale. Reusable from query_data.py, orm_queries.py,
    the Flask app and the PDF builder.
    """
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return fmt_signed(value) if "difference" in label.lower() else fmt_count(value)
    if isinstance(value, (float, Decimal)):
        return fmt_pct(value) if is_percent(label) else fmt_avg(value)
    return str(value)
