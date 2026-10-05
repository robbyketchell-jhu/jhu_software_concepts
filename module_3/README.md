# Module 3: Database Queries, SQLAlchemy, and a Dynamic Webpage

Robby Ketchell · EN.605.256 · GitHub: robbyketchell-jhu

The Module 2 Grad Café data is loaded into PostgreSQL, analysed with raw SQL
(psycopg) and with the SQLAlchemy ORM, and displayed on a Flask page that can
also pull new entries from Grad Café using the Module 2 scraper.

## Files

| File | Purpose |
|------|---------|
| `load_data.py` | Creates the `applicants` table and upserts the cleaned Module 2 data (psycopg) |
| `clean.py` | Cleaning helpers shared by the loader and the scraper pipeline |
| `query_data.py` | Questions 1–11 as raw SQL, run through psycopg |
| `models.py` | SQLAlchemy 2.x `Applicant` model, engine and session factory |
| `orm_queries.py` | The same questions expressed with the SQLAlchemy ORM |
| `formatting.py` | The assignment's number-formatting rules, shared everywhere |
| `app.py`, `templates/index.html`, `static/style.css` | Flask analysis page with **Pull Data** and **Update Analysis** |
| `pull_data.py` | Scrapes new Grad Café entries, cleans them and inserts them (run by Pull Data) |
| `scrape.py` | Module 2 scraper (unchanged) |
| `standardize.py`, `llm_hosting/` | Program/university standardizer for new rows (TinyLlama if installed, rules otherwise) |
| `build_pdfs.py` | Generates `query_results.pdf` and `limitations.pdf` from live results |
| `query_results.pdf`, `limitations.pdf` | Written deliverables |
| `screenshots/` | Raw SQL output, ORM output, running Flask page |
| `requirements.txt`, `github.txt` | Dependencies and repository URL |

`llm_extend_applicant_data_clean.json` is the cleaned, LLM-extended Module 2
dataset (50,000 entries). It is in the ZIP but gitignored because of its size.

## 1. PostgreSQL setup

Any PostgreSQL 14+ works. Two options:

```sh
# Homebrew
brew install postgresql@17 && brew services start postgresql@17

# or Docker
docker run -d --name pg -e POSTGRES_PASSWORD=postgres -p 5432:5432 \
  -v pgdata:/var/lib/postgresql/data postgres:17
```

Connection settings live in a `.env` file next to the code. It is gitignored;
create it yourself:

```
DB_NAME=postgres
DB_USER=robby
DB_PASSWORD=
DB_HOST=localhost
DB_PORT=5432
```

`load_data.py` creates the database named in `DB_NAME` if it does not exist.

## 2. Install

```sh
cd module_3
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## 3. Load the data

```sh
python load_data.py                     # uses llm_extend_applicant_data_clean.json
python load_data.py some_other.json     # or any file in the same shape
```

The loader creates the `applicants` table (p_id primary key, schema from the
assignment) and upserts every record with `ON CONFLICT (p_id) DO UPDATE`, so
running it again never duplicates rows. Cleaning decisions:

- blank / `n/a` / `null` style placeholders become `NULL`;
- dates accept both ISO and the `Sep 12, 2026` display format;
- numeric fields are range-checked and stored as `NULL` when implausible:
  GPA 0–4.0, GRE Quantitative and Verbal 130–170, GRE AW 0–6. About 2,300
  "GRE Quantitative" values were combined scores in the 300s or old-scale
  scores and would have wrecked the averages;
- any record without an id (from `entry_id` or the `/result/<id>` URL) is skipped.

## 4. Raw SQL analysis

```sh
python query_data.py                # all 11 questions
python query_data.py --question 8   # one question
python query_data.py "SELECT COUNT(*) FROM applicants"   # ad-hoc query
```

## 5. SQLAlchemy ORM analysis

```sh
python orm_queries.py              # all questions through the ORM
python orm_queries.py --required   # just 1, 4, 5, 8, 9 and original question 1
```

`orm_queries.py` uses only `select()`, `where()`, `func`, `and_()`, `or_()`
and the `Applicant` model. No `text()` and no cursors. Its output matches
`query_data.py` exactly.

## 6. Flask webpage

```sh
python app.py          # http://127.0.0.1:5000  (PORT=5050 python app.py to change)
```

Every number on the page is read through the ORM (`orm_queries.collect_results`).

- **Update Analysis** (top right) re-queries PostgreSQL and redraws the page.
  It never starts a scrape. If a Pull Data run is active it says so and shows
  the data already committed.
- **Pull Data** starts `pull_data.py` as a subprocess. A second click while
  one is running is refused with a message; the button is disabled and the
  page polls `/status` to show the scraper's progress log.

## 7. Pull Data (scraper integration)

`pull_data.py` reuses `scrape.py` from Module 2, which drives a Chrome window
because Grad Café sits behind Cloudflare. Before clicking Pull Data:

1. Chrome: **View → Developer → Allow JavaScript from Apple Events**
2. Open <https://www.thegradcafe.com/survey> in Chrome and clear the human check
3. Leave that Chrome window frontmost

It then reads the newest results pages until it hits a page where every entry
is already in the database (or 25 pages, `--max-pages`), cleans the rows with
`clean.py`, fills `llm_generated_program` / `llm_generated_university` with
`standardize.py`, and upserts them with the same `load_records()` the loader
uses. Existing rows are never deleted. You can also run it by hand:

```sh
python pull_data.py --max-pages 5
```

`standardize.py` uses the Module 2 TinyLlama standardizer when
`llama-cpp-python` is installed (see `llm_hosting/README.md`); otherwise it
falls back to the same split-and-fuzzy-match rules the standardizer itself
falls back to, using the canonical name lists in `llm_hosting/`.

## 8. PDFs and screenshots

```sh
python build_pdfs.py   # regenerates query_results.pdf and limitations.pdf from the live DB
```

Screenshots in `screenshots/`: `sql_console_output.png`, `orm_console_output.png`,
`flask_webpage.png`.

## 9. SQL versus SQLAlchemy (Question 5)

**Raw SQL** (`query_data.py`):

```sql
SELECT ROUND(
         100.0 * COUNT(*) FILTER (WHERE status ILIKE 'accept%')
         / NULLIF(COUNT(*), 0),
       2) AS "Fall 2025 acceptance percentage"
FROM applicants
WHERE LOWER(TRIM(term)) = 'fall 2025';
```

**SQLAlchemy** (`orm_queries.py`):

```python
FALL_2025 = func.lower(func.trim(Applicant.term)) == "fall 2025"
ACCEPTED = Applicant.status.ilike("accept%")

stmt = select(func.count(), func.count().filter(ACCEPTED)).where(FALL_2025)
total, accepted = session.execute(stmt).one()
percent = 100.0 * accepted / total if total else None   # formatted as 40.74%
```

The ORM version is built from reusable Python expressions: `FALL_2025` and
`ACCEPTED` are defined once and shared by six other questions, the query is
composed and type-checked by Python rather than string-concatenated, and the
same code would run on SQLite or MySQL with a different engine URL. The raw
SQL is shorter and more transparent: everything (the FILTER clause, the
rounding, the NULLIF guard) is visible in one statement, it can be pasted
straight into psql to debug, and the author controls exactly what PostgreSQL
executes instead of relying on how SQLAlchemy renders `func.count().filter()`.
For one-off analysis I found the SQL faster to write and verify; for the
Flask app, where the same filters are reused and results feed templates, the
ORM's composability was worth the extra abstraction.

## Notes

- Credentials are never committed: `.env` is gitignored and the code reads
  only environment variables.
- `module_2/clean.py` was empty in my Module 2 submission; the cleaning for
  newly scraped rows now lives in `module_3/clean.py`.
