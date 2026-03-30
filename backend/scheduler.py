"""APScheduler jobs for reminders and weekly cleanup."""

from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

scheduler = BackgroundScheduler(timezone="Europe/Chisinau")


def cleanup_previous_week(app, db):
    """Delete all selections from last week. Safe to run anytime."""
    with app.app_context():
        from models import Selection
        today = date.today()
        # Get last week's Monday-Friday
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        last_friday = last_monday + timedelta(days=4)
        count = Selection.query.filter(
            Selection.date >= last_monday,
            Selection.date <= last_friday,
        ).delete()
        db.session.commit()
        if count:
            print(f"[Scheduler] Cleaned up {count} selections from {last_monday} - {last_friday}")


def unapprove_past_days(app, db, include_today=False):
    """Un-approve menus for days that have already passed this week."""
    with app.app_context():
        from models import Menu
        today = date.today()
        dow = today.weekday()  # 0=Mon ... 4=Fri
        if dow > 4:
            # Weekend: un-approve all days of the week
            ws = today - timedelta(days=dow)
            count = Menu.query.filter(
                Menu.week_start_date == ws,
                Menu.is_approved == True,
            ).update({"is_approved": False})
        else:
            ws = today - timedelta(days=dow)  # this week's Monday
            cutoff = dow + 1 if include_today else dow
            count = Menu.query.filter(
                Menu.week_start_date == ws,
                Menu.day_of_week < cutoff,
                Menu.is_approved == True,
            ).update({"is_approved": False})
        db.session.commit()
        if count:
            print(f"[Scheduler] Un-approved {count} menus for past days")


def init_scheduler(app, db):
    """Initialize and start the scheduler."""
    # Friday at 23:59 — clean up this week's selections
    scheduler.add_job(
        cleanup_previous_week,
        "cron",
        day_of_week="fri",
        hour=23,
        minute=59,
        args=[app, db],
        id="weekly_cleanup_friday",
        replace_existing=True,
    )

    # Monday at 06:00 — backup cleanup (in case Friday job missed)
    scheduler.add_job(
        cleanup_previous_week,
        "cron",
        day_of_week="mon",
        hour=6,
        minute=0,
        args=[app, db],
        id="weekly_cleanup_monday",
        replace_existing=True,
    )

    # Every day at 23:30 — un-approve menus for today (day is over, include today)
    scheduler.add_job(
        unapprove_past_days,
        "cron",
        hour=23,
        minute=30,
        args=[app, db],
        kwargs={"include_today": True},
        id="unapprove_daily",
        replace_existing=True,
    )

    scheduler.start()

    # Run once at startup to clean up past days (don't include today - might still be active)
    unapprove_past_days(app, db, include_today=False)

    print("[Scheduler] Started")
