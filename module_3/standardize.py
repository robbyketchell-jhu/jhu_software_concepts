"""
Module 3 - standardize.py

Fills in llm-generated-program / llm-generated-university for newly scraped rows.

Preferred path: the Module 2 TinyLlama standardizer (llm_hosting/app.py). It
needs llama-cpp-python and a ~670MB model download, so it is optional.

Fallback: the same rules-first logic the standardizer itself falls back to when
the model returns junk (split "Program, University", fix common abbreviations,
then fuzzy-match against the canonical lists in llm_hosting/).
"""

import difflib
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
CANON_DIR = os.path.join(HERE, "llm_hosting")

try:  # The real model, if llama_cpp is installed.
    os.environ.setdefault("CANON_UNIS_PATH", os.path.join(CANON_DIR, "canon_universities.txt"))
    os.environ.setdefault("CANON_PROGS_PATH", os.path.join(CANON_DIR, "canon_programs.txt"))
    from llm_hosting.app import _call_llm  # noqa: E402

    HAVE_LLM = True
except Exception:  # ImportError, missing model, etc.
    _call_llm = None
    HAVE_LLM = False


def _read_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []


CANON_UNIS = _read_lines(os.path.join(CANON_DIR, "canon_universities.txt"))
CANON_PROGS = _read_lines(os.path.join(CANON_DIR, "canon_programs.txt"))

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


def _best_match(name, candidates, cutoff):
    if not name or not candidates:
        return None
    matches = difflib.get_close_matches(name, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None


def _normalize_university(uni):
    u = re.sub(r"\s+", " ", (uni or "")).strip().strip(",")
    for pattern, full in ABBREVIATIONS.items():
        if re.fullmatch(pattern, u, flags=re.IGNORECASE):
            u = full
            break
    if not u:
        return "Unknown"
    u = re.sub(r"\bOf\b", "of", u.title())
    u = re.sub(r"\bAnd\b", "and", u)
    if u in CANON_UNIS:
        return u
    return _best_match(u, CANON_UNIS, cutoff=0.86) or u


def _normalize_program(prog):
    p = re.sub(r"\s+", " ", (prog or "")).strip().strip(",").title()
    p = re.sub(r"\bAnd\b", "and", p)
    p = re.sub(r"\bOf\b", "of", p)
    if p in CANON_PROGS:
        return p
    return _best_match(p, CANON_PROGS, cutoff=0.84) or p


def rules_standardize(program_text):
    """'Computer Science, Johns Hopkins University' -> (program, university)."""
    text = re.sub(r"\s+", " ", program_text or "").strip()
    if "," in text:
        prog, uni = text.rsplit(",", 1)
    else:
        parts = re.split(r" at | @ ", text, maxsplit=1)
        prog, uni = (parts[0], parts[1]) if len(parts) > 1 else (text, "")
    return _normalize_program(prog), _normalize_university(uni)


def standardize_text(program_text):
    """Returns (standardized_program, standardized_university)."""
    if HAVE_LLM:
        try:
            result = _call_llm(program_text)
            return result["standardized_program"], result["standardized_university"]
        except Exception:
            pass  # fall through to the rules
    return rules_standardize(program_text)


def standardize_rows(rows):
    """Adds llm-generated-program / llm-generated-university to each cleaned row in place."""
    for row in rows:
        prog, uni = standardize_text(row.get("program") or "")
        row["llm-generated-program"] = prog
        row["llm-generated-university"] = uni
    return rows


if __name__ == "__main__":
    import sys

    print("Using:", "TinyLlama standardizer" if HAVE_LLM else "rules-based fallback")
    for arg in sys.argv[1:] or ["Computer Science, JHU", "Electrical Engineering and Computer Science, MIT"]:
        print(arg, "->", standardize_text(arg))
