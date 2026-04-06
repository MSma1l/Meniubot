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
    """Create menu templates for the new week if they don't exist yet.
    Copies structure (name, sort_order) from previous week."""
    with app.app_context():
        from models import Menu
        today = today_md()
        this_monday = today - timedelta(days=today.weekday())

        existing = Menu.query.filter_by(week_start_date=this_monday).first()
        if existing:
            return  # Already exists

        # Copy from previous week
        prev_monday = this_monday - timedelta(days=7)
        prev_menus = Menu.query.filter_by(week_start_date=prev_monday).all()

        if prev_menus:
            for pm in prev_menus:
                menu = Menu(
                    name=pm.name,
                    name_ru=pm.name_ru,
                    sort_order=pm.sort_order,
                    day_of_week=pm.day_of_week,
                    week_start_date=this_monday,
                    is_approved=False,
                )
                db.session.add(menu)
        else:
            menu_templates = [
                {"name": "Lunch 1", "name_ru": "Обед 1", "sort_order": 0},
                {"name": "Lunch 2", "name_ru": "Обед 2", "sort_order": 1},
                {"name": "Dieta", "name_ru": "Диета", "sort_order": 2},
                {"name": "Post", "name_ru": "Пост", "sort_order": 3},
            ]
            for day in range(5):
                for tmpl in menu_templates:
                    menu = Menu(
                        name=tmpl["name"],
                        name_ru=tmpl["name_ru"],
                        sort_order=tmpl["sort_order"],
                        day_of_week=day,
                        week_start_date=this_monday,
                    )
                    db.session.add(menu)
        db.session.commit()
        print(f"[Scheduler] Created menus for week {this_monday}")


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
