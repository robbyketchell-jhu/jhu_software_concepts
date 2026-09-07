from flask import Blueprint, render_template

bp = Blueprint("pages", __name__)

@bp.route("/")
def home():
    return render_template("pages/home.html")

@bp.route("/contact")
def contact():
    return render_template("pages/contact.html")

@bp.route("/projects")
def projects():
    return render_template("pages/projects.html")
