"""Entry point: starts Flask API + scheduler. Bot runs separately."""

import logging
import os
from dotenv import load_dotenv

load_dotenv()

# INFO, nu WARNING-ul implicit: altfel jurnalul de audit al cheilor de serviciu
# (și restul logger.info din app.py) nu apare în `docker compose logs`.
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

from app import app
from models import db
from scheduler import init_scheduler

if __name__ == "__main__":
    init_scheduler(app, db)
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
