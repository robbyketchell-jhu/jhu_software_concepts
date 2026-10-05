"""
Module 3 - clean.py

Cleaning helpers shared by load_data.py (bulk load of the Module 2 dataset) and
pull_data.py (new rows scraped by the Pull Data button).

Two record shapes show up in this project:

  1. The cleaned/LLM-extended dataset from Module 2
     (keys like entry_id, applicant_status, applicant_type, gre_quant, ...).
  2. Raw records straight out of scrape.py
     (keys like university, program, status, student_type, gre, ...).

clean_scraped_record() turns shape 2 into shape 1 so that one loader can
handle both without special cases.
"""

import re
from datetime import datetime

MISSING_DATA_VALUES = {"", "n/a", "na", "none", "null", "nan", "-", "--"}

DATE_FORMATS = ["%Y-%m-%d", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y", "%m/%d/%Y"]

# Plausible ranges. Anything outside is stored as missing rather than kept,
# because a "GRE Quantitative" of 320 is really a combined score and a GPA of
# 9.2 is on a different scale. Those values would poison the averages.
POSSIBLE_SCORES = {
    "gpa": (0.0, 4.0),
    "gre": (130.0, 170.0),
    "gre_v": (130.0, 170.0),
    "gre_aw": (0.0, 6.0),
}


def clean_text(value):
    """
    Replaces missing data with None. If the value is None it returns None,
    otherwise it strips whitespace and returns None when the lowercase text
    matches one of the MISSING_DATA_VALUES placeholders.
    """
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in MISSING_DATA_VALUES else text


def clean_float(value, field):
    """Pull a number out of values like 3.8, '3.80', or 'GPA 3.80', then range-check it."""
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
    """Whole-number ids. Returns None for anything that is not an integer."""
    text = clean_text(value)
    if text is None:
        return None
    match = re.search(r"\d+", text)
    return int(match.group()) if match else None


def clean_date(value):
    """Accepts ISO dates and the 'Sep 12, 2026' style that Grad Cafe displays."""
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
    """https://www.thegradcafe.com/result/1020482 -> 1020482"""
    text = clean_text(url)
    if text is None:
        return None
    match = re.search(r"/result/(\d+)", text)
    return int(match.group(1)) if match else None


def clean_scraped_record(record):
    """
    Converts one raw scrape.py record into the same shape as the cleaned
    Module 2 dataset so load_data.to_row() can handle it.
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
        # Filled in by standardize.py (LLM or rules-based fallback).
        "llm-generated-program": record.get("llm-generated-program"),
        "llm-generated-university": record.get("llm-generated-university"),
    }
