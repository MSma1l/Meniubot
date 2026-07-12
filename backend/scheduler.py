"""APScheduler jobs for reminders and weekly cleanup."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

MOLDOVA_TZ = ZoneInfo("Europe/Chisinau")
scheduler = BackgroundScheduler(timezone="Europe/Chisinau")


def today_md():
    """Get today's date in Moldova timezone."""
    return datetime.now(MOLDOVA_TZ).date()


def cleanup_previous_week(app, db):
    """Delete all selections from last week. Safe to run anytime."""
    with app.app_context():
        from models import Selection
        today = today_md()
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


def seed_weekly_menus(app, db):
    """Create the new week's menus, delegating to app.py's canonical seeder.

    This used to carry its own copy of the seeding logic, which drifted: it
    copied the previous week without `restaurant` and without the Andy's Felul-1
    options, so every Monday the business lunches silently turned into empty
    Șezătoare menus. One implementation, in app.py, is the fix.
    """
    with app.app_context():
        from app import seed_default_menus, ensure_andys_menus, get_week_start
        seed_default_menus()                      # no-op if the week already exists
        ensure_andys_menus(get_week_start())      # backfill Andy's either way
        print(f"[Scheduler] Menus ready for week {get_week_start()}")


def reset_menu_content(app, db):
    """Reset menu content (felul_1, felul_2 text) for the current week.
    Keeps the menu structure (name, sort_order, day_of_week) intact."""
    with app.app_context():
        from models import Menu
        today = today_md()
        this_monday = today - timedelta(days=today.weekday())
        count = Menu.query.filter(
            Menu.week_start_date == this_monday,
        ).update({
            "felul_1": "",
            "felul_2": "",
            "garnitura": "",
            "felul_1_ru": "",
            "felul_2_ru": "",
            "garnitura_ru": "",
            "is_approved": False,
        })
        db.session.commit()
        if count:
            print(f"[Scheduler] Reset content for {count} menus (week {this_monday})")


def unapprove_past_days(app, db, include_today=False):
    """Un-approve menus for days that have already passed this week."""
    with app.app_context():
        from models import Menu
        today = today_md()
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

    # Monday at 02:00 — create menus for the new week + reset content
    scheduler.add_job(
        seed_weekly_menus,
        "cron",
        day_of_week="mon",
        hour=2,
        minute=0,
        args=[app, db],
        id="weekly_seed_menus",
        replace_existing=True,
    )

    scheduler.add_job(
        reset_menu_content,
        "cron",
        day_of_week="mon",
        hour=2,
        minute=1,
        args=[app, db],
        id="weekly_reset_menu_content",
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

    # Run once at startup
    seed_weekly_menus(app, db)  # Ensure menus exist for current week
    unapprove_past_days(app, db, include_today=False)

    print("[Scheduler] Started")
