"""Output formatting rules shared by the console scripts and the web page.

Every number that reaches a user goes through one of these helpers, which is
what guarantees that a percentage is *always* rendered with exactly two
decimal places:

===============  ===========================  ==========
Result           Rule                         Example
===============  ===========================  ==========
Counts           whole number, thousands sep  ``19,290``
Percentages      two decimals plus ``%``      ``50.09%``
Averages         two decimals                 ``3.79``
Differences      signed whole number          ``+3``
===============  ===========================  ==========
"""

from decimal import Decimal

#: Rendered in place of a missing value.
MISSING = "N/A"


def fmt_count(value):
    """Format a whole-number count.

    :param value: an integer-like value, or ``None``.
    :returns: e.g. ``"19,290"``, or ``"N/A"``.
    """
    return MISSING if value is None else f"{int(value):,}"


def fmt_pct(value):
    """Format a percentage already expressed on a 0-100 scale.

    :param value: the percentage, or ``None``.
    :returns: e.g. ``"50.09%"``, or ``"N/A"``.
    """
    return MISSING if value is None else f"{float(value):.2f}%"


def fmt_avg(value):
    """Format an average to two decimal places.

    :param value: the average, or ``None``.
    :returns: e.g. ``"3.79"``, or ``"N/A"``.
    """
    return MISSING if value is None else f"{float(value):.2f}"


def fmt_signed(value):
    """Format a signed whole-number difference.

    :param value: the difference, or ``None``.
    :returns: e.g. ``"+3"``, or ``"N/A"``.
    """
    return MISSING if value is None else f"{int(value):+,}"


def is_percent(label):
    """Report whether a column label denotes a percentage.

    :param label: a column name or alias.
    :returns: ``True`` when the label mentions percent, ``%`` or starts ``pct``.
    """
    label = label.lower()
    return "percent" in label or "%" in label or label.startswith("pct")


def format_value(label, value):
    """Format *value* using the rule implied by its column *label*.

    Integers become counts (or signed differences when the label mentions a
    difference), floats become percentages or averages depending on the label,
    and anything else is passed through as text.

    :param label: the column name or alias driving the choice of rule.
    :param value: the value to render.
    :returns: the formatted string.
    """
    if value is None:
        return MISSING
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return fmt_signed(value) if "difference" in label.lower() else fmt_count(value)
    if isinstance(value, (float, Decimal)):
        return fmt_pct(value) if is_percent(label) else fmt_avg(value)
    return str(value)
