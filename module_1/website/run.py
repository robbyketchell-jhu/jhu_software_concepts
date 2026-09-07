from flask import Flask
from flask import Blueprint
import pages

app = Flask(__name__)
bp = Blueprint("pages", __name__)

if __name__ == "__main__":
    app.register_blueprint(pages.bp)
    app.run(host="0.0.0.0", port=8080, debug=True)