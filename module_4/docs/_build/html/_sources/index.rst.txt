Grad Cafe Analytics
===================

A small analytics service over self-reported graduate admissions results from
`Grad Café <https://www.thegradcafe.com/survey>`_.

It has two subsystems:

**Web (Flask)**
   Serves an Analysis page with two buttons, *Pull Data* and *Update
   Analysis*, and a small JSON API behind them.

**Data (ETL and database)**
   Scrapes, cleans and loads rows into PostgreSQL, then computes the summary
   analysis the page displays.

Every number on the page is read through the SQLAlchemy ``Applicant`` model,
and every percentage is rendered with exactly two decimal places.

.. toctree::
   :maxdepth: 2
   :caption: Contents

   overview
   architecture
   testing
   operations
   troubleshooting
   api

Indices
-------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
