"""Sphinx configuration for the Grad Cafe analytics documentation."""

import os
import sys
from datetime import date

# The application package lives one level up, in module_4/src.
sys.path.insert(0, os.path.abspath(".."))

project = "Grad Cafe Analytics"
author = "Robby Ketchell"
copyright = f"{date.today().year}, {author}"
release = "4.0"
version = release

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autosummary",
]

autosummary_generate = True
autodoc_member_order = "bysource"
autodoc_typehints = "description"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

# Importing src pulls in Flask, SQLAlchemy and psycopg. They are all in
# requirements.txt, so nothing needs mocking on Read the Docs.
autodoc_mock_imports = []

napoleon_google_docstring = True
napoleon_numpy_docstring = False

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "flask": ("https://flask.palletsprojects.com/en/stable/", None),
    "sqlalchemy": ("https://docs.sqlalchemy.org/en/20/", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

html_theme = "sphinx_rtd_theme"
html_static_path = []
html_title = "Grad Cafe Analytics"
html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 3,
}

nitpick_ignore_regex = [("py:class", r".*")]
