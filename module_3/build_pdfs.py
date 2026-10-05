"""
Module 3 - build_pdfs.py

Generates the two written deliverables from live database results so the
numbers in the PDFs always match query_data.py:

    query_results.pdf   all 11 questions: wording, result, SQL, explanation
    limitations.pdf     two paragraphs on the limits of self-reported data

Usage:
    python build_pdfs.py
"""

import json
import os
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from clean import POSSIBLE_SCORES
from query_data import QUESTIONS, format_results, run_query

HERE = os.path.dirname(os.path.abspath(__file__))
SOURCE_FILE = os.path.join(HERE, os.getenv("DATA_FILE", "llm_extend_applicant_data_clean.json"))

styles = getSampleStyleSheet()
BODY = ParagraphStyle("body", parent=styles["BodyText"], fontSize=10.5, leading=15, alignment=TA_JUSTIFY, spaceAfter=8)
LABEL = ParagraphStyle("label", parent=styles["BodyText"], fontSize=9, leading=12, textColor=colors.HexColor("#5f6b7a"), spaceBefore=6, spaceAfter=2)
RESULT = ParagraphStyle("result", parent=styles["BodyText"], fontSize=11, leading=15, textColor=colors.HexColor("#0b3a63"), fontName="Helvetica-Bold", leftIndent=12)
CODE = ParagraphStyle("code", parent=styles["Code"], fontSize=7.6, leading=9.6, leftIndent=8, backColor=colors.HexColor("#f4f6f9"), borderPadding=5)
H1 = styles["Title"]
H2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=12.5, leading=16, textColor=colors.HexColor("#0f4c81"), spaceBefore=14)

# Extra context for the Question 9 write-up, per the assignment.
Q9_NOTE = (
    "Why the counts may or may not differ: the two queries only disagree where the raw program "
    "text and the LLM-standardized fields describe the same entry differently. The original-field "
    "match depends on applicants typing a recognisable university name ('MIT', 'Carnegie Mellon', "
    "'Stanford University') and the words 'Computer Science' somewhere in the program string, so an "
    "entry written as 'CS, Stanford' or with a misspelling would be missed. The LLM field collapses "
    "spelling and abbreviation variants onto canonical names, which can add entries the raw match "
    "missed, but it can also drop entries when the model mislabels the university or rewrites the "
    "program (for example turning 'EECS' into a name without the phrase 'Computer Science') or "
    "hallucinates a different school for an ambiguous string. In this dataset the entries for these "
    "four highly ranked programs are already written cleanly on Grad Cafe, so both approaches select "
    "the same rows and the difference is zero. With messier free text the LLM count would usually be "
    "the larger of the two."
)


def table_flowable(columns, rows):
    data = [columns] + rows
    t = Table(data, hAlign="LEFT", repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f4f8")),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, colors.HexColor("#0f4c81")),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#e1e6ec")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_query_results(path):
    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                            topMargin=0.8 * inch, bottomMargin=0.8 * inch,
                            title="Module 3 - SQL Query Results", author="Robby Ketchell")
    story = [
        Paragraph("Module 3: SQL Query Results", H1),
        Paragraph(f"Robby Ketchell &middot; EN.605.256 &middot; generated {date.today().isoformat()} from the live "
                  "PostgreSQL <b>applicants</b> table using query_data.py (psycopg).", BODY),
        Paragraph("Formatting: counts are whole numbers, percentages have two decimal places and a % sign, "
                  "averages have two decimal places. Averages include only applicants who report that metric. "
                  "All text matching is case-insensitive.", BODY),
    ]

    for q in QUESTIONS:
        columns, rows = run_query(q.sql)
        block = [Paragraph(f"Question {q.number}", H2), Paragraph(q.title, BODY), Paragraph("Result", LABEL)]
        if len(rows) == 1:
            block.extend(Paragraph(line, RESULT) for line in format_results(columns, rows))
        else:
            formatted = format_results(columns, rows)
            # format_results renders a text table; rebuild it as a real table for the PDF.
            cells = [[c.strip() for c in line.split(" | ")] for line in formatted[2:-1]]
            block.append(table_flowable(columns, cells))
        block.append(Paragraph("SQL", LABEL))
        block.append(Preformatted(q.sql.strip(), CODE))
        block.append(Paragraph("Explanation", LABEL))
        block.append(Paragraph(q.explanation, BODY))
        if q.number == 9:
            block.append(Paragraph(Q9_NOTE, BODY))
        story.append(KeepTogether(block))
        story.append(Spacer(1, 6))

    doc.build(story)


def profile_numbers():
    """The handful of figures the reflection cites, read live so they stay consistent."""
    (total, with_gpa, with_gre, with_nat, international, phd, fall25, fall25_acc, avg_gre), = run_query("""
        SELECT COUNT(*),
               COUNT(gpa),
               COUNT(gre),
               COUNT(*) FILTER (WHERE us_or_international IS NOT NULL AND TRIM(us_or_international) <> ''),
               COUNT(*) FILTER (WHERE LOWER(TRIM(us_or_international)) = 'international'),
               COUNT(*) FILTER (WHERE degree ~* 'ph\\.?\\s?d'),
               COUNT(*) FILTER (WHERE LOWER(TRIM(term)) = 'fall 2025'),
               COUNT(*) FILTER (WHERE LOWER(TRIM(term)) = 'fall 2025' AND status ILIKE 'accept%'),
               AVG(gre)
        FROM applicants
    """)[1]

    # Out-of-range values that the loader turned into NULL, counted from the source file.
    bad_gre = bad_gpa = None
    if os.path.exists(SOURCE_FILE):
        with open(SOURCE_FILE, encoding="utf-8") as f:
            records = json.load(f)
        lo, hi = POSSIBLE_SCORES["gre"]
        bad_gre = sum(1 for r in records if isinstance(r.get("gre_quant"), (int, float)) and not lo <= r["gre_quant"] <= hi)
        lo, hi = POSSIBLE_SCORES["gpa"]
        bad_gpa = sum(1 for r in records if isinstance(r.get("gpa"), (int, float)) and not lo <= r["gpa"] <= hi)

    return {
        "total": total,
        "gpa_pct": 100.0 * with_gpa / total,
        "gre_pct": 100.0 * with_gre / total,
        "with_gre": with_gre,
        "intl_pct": 100.0 * international / with_nat,
        "phd_pct": 100.0 * phd / total,
        "fall25_acc_pct": 100.0 * fall25_acc / fall25,
        "avg_gre": float(avg_gre),
        "bad_gre": bad_gre,
        "bad_gpa": bad_gpa,
    }


def build_limitations(path):
    n = profile_numbers()
    bad_gre = f"{n['bad_gre']:,}" if n["bad_gre"] is not None else "more than two thousand"
    bad_gpa = f"{n['bad_gpa']:,}" if n["bad_gpa"] is not None else "a couple of hundred"

    para1 = (
        f"The first limitation is that nobody is sampled onto Grad Caf&eacute;; people select themselves in. "
        f"The {n['total']:,} entries in my database are not a sample of graduate applicants, they are a sample "
        f"of applicants who know the site exists, who care enough about the outcome to announce it, and who "
        f"applied to the kinds of programs where posting is a norm. That shows up immediately in the analysis: "
        f"{n['phd_pct']:.1f}% of entries are PhD applications, and my second original question found that the "
        f"ten most-mentioned universities for Fall 2026 are all highly selective research universities such as "
        f"Stanford, Berkeley, Yale, Princeton and MIT. Applicants to regional master's programs, professional "
        f"degrees, or schools outside the United States and Canada are largely absent, so a figure like "
        f"\"{n['intl_pct']:.2f}% international\" describes who posts, not who applies. Outcome also drives "
        f"posting behaviour. An acceptance from a famous program is something people want to share, a "
        f"rejection is something people post to commiserate, and a middling or undecided result is often never "
        f"posted at all, while a single applicant with ten results may post all ten and count ten times. My "
        f"Fall 2025 acceptance percentage of {n['fall25_acc_pct']:.2f}% is therefore a statement about "
        f"submitted entries, and it cannot be read as an admission rate for any program or for applicants in "
        f"general, because both the numerator and the denominator depend on who felt like typing their result "
        f"into a website."
    )
    para2 = (
        f"The second limitation is that every field is self-reported, anonymous, and optional, so the data "
        f"are both incomplete and unverifiable. Only {n['gpa_pct']:.1f}% of entries report a GPA and only "
        f"{n['gre_pct']:.1f}% ({n['with_gre']:,} entries) report a usable GRE Quantitative score, and the people "
        f"who fill in those boxes are plausibly the ones with numbers worth showing. That is the most likely "
        f"explanation for the average GRE Quantitative score of {n['avg_gre']:.2f} in my database, when the "
        f"ETS reference population averages roughly 157: it does not mean applicants score 166 on average, it "
        f"means applicants who volunteer a score on Grad Caf&eacute; do, and with many programs now GRE-optional "
        f"the few who still report are a particularly strong group. The values that are reported are also "
        f"inconsistent. While loading the data I found {bad_gre} \"GRE Quantitative\" values outside the "
        f"130&ndash;170 range (mostly combined totals in the 300s or old 200&ndash;800 scores) and {bad_gpa} "
        f"GPAs above 4.0, which I converted to missing; GPAs on 4.3, 5.0 or 10-point scales that happen to "
        f"fall at or below 4.0 are indistinguishable from US GPAs and silently distort the averages. "
        f"Universities and programs are free text (\"MIT\", \"Massachusetts Institute of Technology (MIT)\", "
        f"\"Johns Hopkins University (Hot Piss Law)\" all appear), which is why Questions 8 and 9 had to be "
        f"matched with patterns and LLM-standardized names, and nothing stops a user from entering a fake or "
        f"duplicate result. The right way to read this database is descriptive rather than inferential: it "
        f"mathematically contains an average GPA of 3.75 among entries that report one, but it does not "
        f"support the claim that graduate applicants, or even admitted students, have an average GPA of 3.75. "
        f"Each number is accurate about the posts and only suggestive about the world."
    )

    doc = SimpleDocTemplate(path, pagesize=letter, leftMargin=1 * inch, rightMargin=1 * inch,
                            topMargin=0.9 * inch, bottomMargin=0.9 * inch,
                            title="Module 3 - Limitations of Self-Reported Data", author="Robby Ketchell")
    doc.build([
        Paragraph("Limitations of Analyzing Self-Reported Grad Caf&eacute; Data", H1),
        Paragraph(f"Robby Ketchell &middot; EN.605.256 Module 3 &middot; {date.today().isoformat()}", BODY),
        Spacer(1, 6),
        Paragraph(para1, BODY),
        Paragraph(para2, BODY),
    ])


def main():
    build_query_results(os.path.join(HERE, "query_results.pdf"))
    print("wrote query_results.pdf")
    build_limitations(os.path.join(HERE, "limitations.pdf"))
    print("wrote limitations.pdf")


if __name__ == "__main__":
    main()
