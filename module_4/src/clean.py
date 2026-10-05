"""Normalisation helpers for Grad Cafe rows.

Two record shapes travel through the system:

1. The cleaned/LLM-extended dataset produced in Module 2, whose keys are
   ``entry_id``, ``applicant_status``, ``applicant_type``, ``gre_quant`` and
   so on.
2. Raw records straight out of :mod:`src.scrape`, whose keys are
   ``university``, ``program``, ``status``, ``student_type``, ``gre`` ...

:func:`clean_scraped_record` converts shape 2 into shape 1 so that a single
loader can handle both without special cases.
"""

import re
from datetime import datetime

#: Placeholder strings that are treated as "no value supplied".
MISSING_DATA_VALUES = {"", "n/a", "na", "none", "null", "nan", "-", "--"}

#: Date formats accepted by :func:`clean_date`, tried in order.
DATE_FORMATS = ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y"]

#: Plausible ``(low, high)`` ranges per numeric field.
#:
#: Anything outside the range is stored as missing rather than kept, because a
#: "GRE Quantitative" of 320 is really a combined score and a GPA of 9.2 is on
#: a different scale. Those values would otherwise poison the averages.
POSSIBLE_SCORES = {
    "gpa": (0.0, 4.0),
    "gre": (130.0, 170.0),
    "gre_v": (130.0, 170.0),
    "gre_aw": (0.0, 6.0),
}


def clean_text(value):
    """Strip a text value and map placeholders to ``None``.

    :param value: any value; non-strings are coerced with :func:`str`.
    :returns: the stripped text, or ``None`` when the value is missing or is
        one of :data:`MISSING_DATA_VALUES`.
    """
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in MISSING_DATA_VALUES else text


def clean_float(value, field):
    """Pull a number out of *value* and range-check it against *field*.

    Accepts real numbers as well as strings such as ``"3.80"`` or
    ``"GPA 3.80"``.

    :param value: the raw value.
    :param field: key into :data:`POSSIBLE_SCORES` naming the valid range.
    :returns: the number as a float, or ``None`` when absent or out of range.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = clean_text(value)
        if text is None:
            return None
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None
        number = float(match.group())
    low, high = POSSIBLE_SCORES[field]
    return number if low <= number <= high else None


def clean_int(value):
    """Extract a whole number from *value*.

    :param value: the raw value.
    :returns: the integer, or ``None`` when no digits are present.
    """
    text = clean_text(value)
    if text is None:
        return None
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def clean_date(value):
    """Parse a date written in any of :data:`DATE_FORMATS`.

    A leading ``"Added on "`` prefix is tolerated.

    :param value: the raw value.
    :returns: a :class:`datetime.date`, or ``None`` when unparseable.
    """
    text = clean_text(value)
    if text is None:
        return None
    text = re.sub(r"^added on\s*", "", text, flags=re.IGNORECASE)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def entry_id_from_url(url):
    """Extract the Grad Cafe entry id from a result URL.

    ``https://www.thegradcafe.com/result/1020482`` yields ``1020482``.

    :param url: the result URL.
    :returns: the id as an integer, or ``None``.
    """
    text = clean_text(url)
    if text is None:
        return None
    match = re.search(r"/result/(\d+)", text)
    return int(match.group(1)) if match else None


def clean_scraped_record(record):
    """Convert one raw :mod:`src.scrape` record into loader shape.

    The ``llm-generated-*`` keys are carried through untouched so that
    :mod:`src.standardize` can fill them in either before or after cleaning.

    :param record: a raw scraped record.
    :returns: a dict using the cleaned Module 2 key names.
    """
    program_name = clean_text(record.get("program"))
    university = clean_text(record.get("university"))
    program = ", ".join(part for part in (program_name, university) if part)

    return {
        "program": program or None,
        "program_name": program_name,
        "university": university,
        "degree": clean_text(record.get("degree")),
        "comments": clean_text(record.get("comments")),
        "date_added": clean_date(record.get("date_added")),
        "url": clean_text(record.get("url")),
        "applicant_status": clean_text(record.get("status")),
        "term": clean_text(record.get("semester_start")),
        "applicant_type": clean_text(record.get("student_type")),
        "gpa": clean_float(record.get("gpa"), "gpa"),
        "gre_quant": clean_float(record.get("gre"), "gre"),
        "gre_verbal": clean_float(record.get("gre_v"), "gre_v"),
        "gre_aw": clean_float(record.get("gre_aw"), "gre_aw"),
        "entry_id": entry_id_from_url(record.get("url")),
        "llm-generated-program": record.get("llm-generated-program"),
        "llm-generated-university": record.get("llm-generated-university"),
    }
