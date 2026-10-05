# Module 4: Pytest and Sphinx

Robby Ketchell · EN.605.256 · GitHub: robbyketchell-jhu

An automated test suite and published documentation for the Grad Café
analytics service built in Module 3. The application code moved into `src/`,
all tests live in `tests/`, and coverage of `src/` is enforced at 100 percent.

**Documentation:** built HTML is committed at
[`docs/_build/html/index.html`](docs/_build/html/index.html); open it directly
or rebuild with the commands below. Read the Docs is configured by
[`.readthedocs.yaml`](../.readthedocs.yaml) at the repository root and will
publish once the repository is made public and connected to a Read the Docs
project; the published URL goes here when that is done.

```
module_4/
├── src/            application code: Flask, ETL, database, queries
├── tests/          all test code
├── docs/           Sphinx project (source + conf.py + built HTML)
├── llm_hosting/    vendored Module 2 standardizer (optional, not under test)
├── pytest.ini      markers and coverage gate
├── requirements.txt
├── coverage_summary.txt
└── README.md
```

## Quick start

```sh
cd module_4
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL=postgresql+psycopg://$USER@localhost:5432/gradcafe
python -m src.load_data ../module_3/llm_extend_applicant_data_clean.json
python -m src.flask_app          # http://127.0.0.1:5000
```

## Configuration

Everything comes from the environment; per the reqirments no credential is ever committed.

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | built from `DB_*` | PostgreSQL URL. `postgres://` and `postgresql://` are rewritten onto the psycopg driver. |
| `TEST_DATABASE_URL` | `DATABASE_URL` | Used only by tests. The suite appends `_test` to the database name, so tests can never write to development data. |
| `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` | `postgres`, empty, `localhost`, `5432`, `gradcafe` | Used only when `DATABASE_URL` is unset; kept for the Module 3 `.env`. |
| `PORT`, `FLASK_DEBUG` | `5000`, unset | Development server. |

## Running the tests

```sh
cd module_4
pytest                                                       # whole suite + coverage gate
pytest -m "web or buttons or analysis or db or integration"  # identical selection
pytest -m web                                                # one subsystem
```

Run pytest **from `module_4/`**. The assignment's example `pytest.ini` spells
the coverage source as `module_4/src`, which only resolves when pytest starts
at the repository root; because `pytest.ini` itself lives in `module_4/`, this
project uses `--cov=src`, which is the same tree seen from here. The CI
workflow does the same with `working-directory: module_4`.

### Markers

Every one of the 285 tests carries at least one marker; there are no unmarked
tests, so the marker expression above selects the entire suite.

| Marker | Covers | Files |
|---|---|---|
| `web` | App factory, routes, page rendering | `test_flask_page.py` |
| `buttons` | Button endpoints, busy gating, error paths | `test_buttons.py` |
| `analysis` | `Answer:` labels, two-decimal formatting, SQL and ORM query layers | `test_analysis_format.py`, `test_query_layer.py` |
| `db` | Schema, inserts, idempotency, selects, and the ETL feeding them | `test_db_insert.py`, `test_etl_units.py`, `test_scrape.py`, `test_config_and_models.py`, `test_cli_entrypoints.py` |
| `integration` | End-to-end pull → update → render | `test_integration_end_to_end.py` |

### What the tests guarantee

- `GET /analysis` returns 200 and renders "Analysis", both buttons and at
  least one `Answer:` label.
- `POST /pull-data` returns 202 with `{"ok": true}` when idle and hands the
  scraper's rows to the loader; 409 with `{"busy": true}` when a pull is
  running.
- `POST /update-analysis` returns 200 when idle and 409 with `{"busy": true}`
  mid-pull, performing no update in that case.
- Every percentage anywhere on the page carries exactly two decimals.
- After a pull, rows exist in PostgreSQL with the required Module 3 schema and
  non-null required fields.
- Duplicate pulls do not duplicate rows (uniqueness key `p_id`).
- `fetch_applicant` returns a dict with exactly the required field names.
- A loader failure yields 500 and leaves nothing partly written.

No test reaches the network, launches a browser, or sleeps. Busy state is
exercised by calling `PullState.begin()` directly; the whole suite runs in
about three seconds.

### Coverage

`pytest.ini` sets `--cov-fail-under=100`, so a run that leaves any line of
`src/` untested fails. The committed terminal output is in
[coverage_summary.txt](coverage_summary.txt).

```
TOTAL   848 stmts   0 miss   186 branch   0 partial   100%
```

## Testability

- **`create_app(...)` factory** in [src/flask_app.py](src/flask_app.py) takes
  `scraper`, `loader`, `analysis`, `run_async`, `max_pages` and
  `database_url` as keyword arguments, so tests inject fakes.
- **Stable selectors**: `data-testid="pull-data-btn"` and
  `data-testid="update-analysis-btn"`, plus `result-<n>`, `answer-value`,
  `job-status` and `analysis-error`. The two button ids are exported as
  constants so no test hard-codes them.
- **Observable busy state**: `PullState` exposes `begin()`, `finish()` and
  `snapshot()`, and `GET /status` returns the snapshot.
- **Injected collaborators everywhere**: the scraper takes a browser object,
  the waiting loops take `clock` and `sleeper`, and the Chrome driver takes a
  `runner` in place of `subprocess.run`.

## Continuous integration

[`.github/workflows/tests.yml`](../.github/workflows/tests.yml) at the
repository root starts a PostgreSQL 17 service, installs
`module_4/requirements.txt`, runs the marked suite with coverage, and builds
the Sphinx docs with warnings as errors.

Both jobs pass green: [run 37323717481](https://github.com/robbyketchell-jhu/jhu_software_concepts/actions/runs/37323717481)
(285 passed, 100.00% coverage). [actions_success.png](actions_success.png)
shows that run; because the repository is private, the image is rendered from
the run's GitHub Actions API record rather than captured from the Actions web
page, and it states as much at the foot of the image.

## Documentation

Built with Sphinx (autodoc + napoleon + the Read the Docs theme):

```sh
cd module_4/docs
sphinx-build -b html . _build/html
open _build/html/index.html
```

Pages: Overview and setup, Architecture, Testing guide, Operational notes,
Troubleshooting, and an API reference with autodoc for every module including
`scrape.py`, `clean.py`, `load_data.py`, `query_data.py` and the Flask routes.
Read the Docs builds from [`.readthedocs.yaml`](../.readthedocs.yaml).

## Changes from Module 3

- Code moved into `src/` as an importable package with relative imports.
- `app.py` became `src/flask_app.py` with a `create_app` factory; the buttons
  now post JSON and return 202/200/409 instead of redirecting with flash
  messages.
- Connections are configured from `DATABASE_URL` rather than only `DB_*`.
- `scrape.py` split: the AppleScript driver moved to `src/browser.py` and the
  paging loop takes the browser as a parameter.
- The SQLAlchemy engine is lazy and resettable so tests can repoint it.
- The database schema and required fields are unchanged.
- PDF generation (`build_pdfs.py`) stayed in `module_3`; it is a Module 3
  deliverable, not part of the service under test.
