# Personal Portfolio Site

Module 1: Personal Website in Flask

## Description

A multi-page personal website built with Flask and Jinja templates. Pages
share a single base.html layout and a navigation menu on the top right
The nav is defined once and the current page is highlighted
automatically by matching each link against the active Flask endpoint.

Routes are organized in a Flask Blueprint, which keeps the URL definitions in one module and makes
the endpoint names static/constant if the paths change later. Stling is in a single styles.css
file.

## Usage

Clone the repository and change into the project directory:

```bash
git clone git@github.com:robbyketchell-jhu/jhu_software_concepts.git
cd module_1/website
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Run the application:

```bash
python run.py
```

The website will be available at http://0.0.0.0:8080.
