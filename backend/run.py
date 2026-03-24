"""Entry point: starts Flask API + scheduler. Bot runs separately."""

import os
from dotenv import load_dotenv

load_dotenv()

from app import app
from models import db
from scheduler import init_scheduler

if __name__ == "__main__":
    init_scheduler(app, db)
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
