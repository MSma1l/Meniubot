"""APScheduler jobs for reminders and weekly cleanup."""

import os
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler()


def cleanup_weekly_selections(app, db):
    """Delete all selections from the current (ending) week. Runs Friday 23:59."""
    with app.app_context():
        from models import Selection
        week_start = date.today() - timedelta(days=date.today().weekday())
        week_end = week_start + timedelta(days=4)
        Selection.query.filter(
            Selection.date >= week_start,
            Selection.date <= week_end,
        ).delete()
        db.session.commit()
        print(f"[Scheduler] Cleaned up selections for week {week_start} - {week_end}")


def init_scheduler(app, db):
    """Initialize and start the scheduler."""
    # Friday at 23:59 — clean up selections
    scheduler.add_job(
        cleanup_weekly_selections,
        "cron",
        day_of_week="fri",
        hour=23,
        minute=59,
        args=[app, db],
        id="weekly_cleanup",
        replace_existing=True,
    )

    scheduler.start()
    print("[Scheduler] Started")
