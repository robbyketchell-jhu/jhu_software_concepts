"""Fill in the LLM-generated program and university names for new rows.

Two strategies, picked at import time:

* the Module 2 TinyLlama standardizer in ``llm_hosting/app.py``, when
  ``llama-cpp-python`` and the model are installed, and
* a rules-first fallback - the same split, abbreviation expansion and fuzzy
  match against the canonical name lists that the standardizer itself falls
  back to when the model returns something unusable.

The fallback is pure Python with no network access, so tests exercise it
directly and CI never downloads a model.
"""

import difflib
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
#: Directory holding ``canon_universities.txt`` and ``canon_programs.txt``.
CANON_DIR = os.path.join(os.path.dirname(HERE), "llm_hosting")


def _load_llm():
    """Import the TinyLlama standardizer if it is available.

    :returns: the ``_call_llm`` callable, or ``None`` when unavailable.
    """
    os.environ.setdefault("CANON_UNIS_PATH", os.path.join(CANON_DIR, "canon_universities.txt"))
    os.environ.setdefault("CANON_PROGS_PATH", os.path.join(CANON_DIR, "canon_programs.txt"))
    try:  # pragma: no cover - depends on an optional heavyweight dependency
        from llm_hosting.app import _call_llm

        return _call_llm
    except Exception:  # pragma: no cover - the usual path in CI
        return None


#: The TinyLlama entry point, or ``None`` when the model is not installed.
CALL_LLM = _load_llm()
#: Whether the real model is available.
HAVE_LLM = CALL_LLM is not None


def read_lines(path):
    """Read non-empty, stripped lines from *path*.

    :param path: file to read.
    :returns: the list of lines, or ``[]`` when the file is missing.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            return [line.strip() for line in handle if line.strip()]
    except FileNotFoundError:
        return []


#: Canonical university names used for fuzzy matching.
CANON_UNIS = read_lines(os.path.join(CANON_DIR, "canon_universities.txt"))
#: Canonical program names used for fuzzy matching.
CANON_PROGS = read_lines(os.path.join(CANON_DIR, "canon_programs.txt"))

#: Whole-string abbreviations expanded before matching.
ABBREVIATIONS = {
    r"^mit$": "Massachusetts Institute of Technology",
    r"^massachusetts institute of technology \(mit\)$": "Massachusetts Institute of Technology",
    r"^cmu$": "Carnegie Mellon University",
    r"^carnegie mellon$": "Carnegie Mellon University",
    r"^jhu$": "Johns Hopkins University",
    r"^johns hopkins$": "Johns Hopkins University",
    r"^stanford$": "Stanford University",
    r"^georgetown$": "Georgetown University",
    r"^ubc$": "University of British Columbia",
    r"^uoft$": "University of Toronto",
    r"^mcg(ill)?\.?$": "McGill University",
}


def best_match(name, candidates, cutoff):
    """Return the closest canonical name, or ``None``.

    :param name: the name to match.
    :param candidates: canonical names to match against.
    :param cutoff: minimum similarity, 0-1.
    :returns: the matched name, or ``None``.
    """
    if not name or not candidates:
        return None
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def normalize_university(uni):
    """Expand, capitalise and canonicalise a university name.

    :param uni: the raw university text.
    :returns: the standardised name, or ``"Unknown"`` when empty.
    """
    text = re.sub(r"\s+", " ", (uni or "")).strip().strip(",")
    for pattern, full in ABBREVIATIONS.items():
        if re.fullmatch(pattern, text, flags=re.IGNORECASE):
            text = full
            break
    if not text:
        return "Unknown"
    text = re.sub(r"\bOf\b", "of", text.title())
    text = re.sub(r"\bAnd\b", "and", text)
    if text in CANON_UNIS:
        return text
    return best_match(text, CANON_UNIS, cutoff=0.86) or text


def normalize_program(prog):
    """Capitalise and canonicalise a program name.

    :param prog: the raw program text.
    :returns: the standardised name.
    """
    text = re.sub(r"\s+", " ", (prog or "")).strip().strip(",").title()
    text = re.sub(r"\bAnd\b", "and", text)
    text = re.sub(r"\bOf\b", "of", text)
    if text in CANON_PROGS:
        return text
    return best_match(text, CANON_PROGS, cutoff=0.84) or text


def rules_standardize(program_text):
    """Split a combined program string into program and university.

    ``"Computer Science, Johns Hopkins University"`` becomes
    ``("Computer Science", "Johns Hopkins University")``.

    :param program_text: the combined text.
    :returns: a ``(program, university)`` tuple.
    """
    text = re.sub(r"\s+", " ", program_text or "").strip()
    if "," in text:
        prog, uni = text.rsplit(",", 1)
    else:
        parts = re.split(r" at | @ ", text, maxsplit=1)
        prog, uni = (parts[0], parts[1]) if len(parts) > 1 else (text, "")
    return normalize_program(prog), normalize_university(uni)


def standardize_text(program_text, call_llm=None):
    """Standardise one combined program string.

    :param program_text: the combined text.
    :param call_llm: override for the TinyLlama entry point; injected by
        tests. Defaults to :data:`CALL_LLM`.
    :returns: a ``(program, university)`` tuple.
    """
    call_llm = CALL_LLM if call_llm is None else call_llm
    if call_llm is not None:
        try:
            result = call_llm(program_text)
            return result["standardized_program"], result["standardized_university"]
        except Exception:
            pass  # fall through to the rules
    return rules_standardize(program_text)


def standardize_rows(rows, call_llm=None):
    """Add the two ``llm-generated-*`` keys to each cleaned row, in place.

    :param rows: cleaned records carrying a ``program`` key.
    :param call_llm: forwarded to :func:`standardize_text`.
    :returns: the same list, for chaining.
    """
    for row in rows:
        prog, uni = standardize_text(row.get("program") or "", call_llm=call_llm)
        row["llm-generated-program"] = prog
        row["llm-generated-university"] = uni
    return rows
