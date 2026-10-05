API reference
=============

Autodoc pages for every module under ``module_4/src``.

Web layer
---------

flask_app
^^^^^^^^^

The application factory, the routes and the busy-state machinery.

.. automodule:: src.flask_app
   :members:
   :undoc-members:
   :show-inheritance:

Analysis layer
--------------

query_data
^^^^^^^^^^

The eleven analysis questions as raw SQL, plus the simple query functions the
template relies on.

.. automodule:: src.query_data
   :members:
   :undoc-members:
   :show-inheritance:

orm_queries
^^^^^^^^^^^

The same questions expressed with the SQLAlchemy ORM.

.. automodule:: src.orm_queries
   :members:
   :undoc-members:
   :show-inheritance:

formatting
^^^^^^^^^^

The output rules that keep every percentage at two decimal places.

.. automodule:: src.formatting
   :members:
   :undoc-members:

ETL layer
---------

scrape
^^^^^^

URL building, ``robots.txt`` checking, HTML parsing and the paging loop.

.. automodule:: src.scrape
   :members:
   :undoc-members:
   :show-inheritance:

browser
^^^^^^^

The AppleScript Chrome driver the scraper talks to.

.. automodule:: src.browser
   :members:
   :undoc-members:
   :show-inheritance:

clean
^^^^^

Normalisation of raw scraped rows into loader shape.

.. automodule:: src.clean
   :members:
   :undoc-members:

standardize
^^^^^^^^^^^

Canonical program and university names, by model or by rules.

.. automodule:: src.standardize
   :members:
   :undoc-members:

pull_data
^^^^^^^^^

The pipeline behind the Pull Data button.

.. automodule:: src.pull_data
   :members:
   :undoc-members:

Database layer
--------------

load_data
^^^^^^^^^

Table creation and the psycopg upsert.

.. automodule:: src.load_data
   :members:
   :undoc-members:

models
^^^^^^

The SQLAlchemy ``Applicant`` model, engine and session factory.

.. automodule:: src.models
   :members:
   :undoc-members:
   :show-inheritance:

config
^^^^^^

``DATABASE_URL`` handling.

.. automodule:: src.config
   :members:
   :undoc-members:
