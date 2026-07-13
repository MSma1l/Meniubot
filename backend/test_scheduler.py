"""Teste pentru joburile cron (scheduler.py).

Rulează: python -m unittest test_scheduler -v

Folosește o bază SQLite temporară (ștearsă la final) și fixează ziua peste tot
unde contează, ca rezultatele să nu depindă de ziua în care rulează suita.
"""

import os
import tempfile
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

# Variabilele de mediu trebuie setate ÎNAINTE de `import app` (le citește la import,
# și tot atunci creează tabelele + face seed pe săptămâna curentă).
_TMP_DIR = tempfile.mkdtemp(prefix="meniubot-test-")
os.environ.setdefault("SECRET_KEY", "0" * 32)
os.environ.setdefault("INTERNAL_API_TOKEN", "internal-test-token")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("ADMIN_PASSWORD", "admin")
os.environ.setdefault("DATABASE_URL", "sqlite:///" + os.path.join(_TMP_DIR, "test.db"))

import app as app_module  # noqa: E402
import scheduler as sched  # noqa: E402
from models import (  # noqa: E402
    db, FelSelectat, Menu, MenuOption, Restaurant, Selection, User,
)


def tearDownModule():
    # Deliberately empty. app.py binds the database at import, so every test module in
    # this process shares one file. Deleting it here killed whichever module ran next
    # ("attempt to write a readonly database") — and which module that is depends on
    # the order the files are named on the command line. It's a tempfile; the OS
    # reclaims it.
    pass


# Zile fixe folosite în teste (2026-03-02 e o luni).
MONDAY = date(2026, 3, 2)
WEDNESDAY = date(2026, 3, 4)
FRIDAY = date(2026, 3, 6)
SATURDAY = date(2026, 3, 7)
PREV_MONDAY = MONDAY - timedelta(days=7)


class SchedulerTestCase(unittest.TestCase):
    """Bază: bază de date curată + zi fixată în ambele module."""

    today = WEDNESDAY

    def setUp(self):
        self.app = app_module.app
        self.ctx = self.app.app_context()
        self.ctx.push()
        # All test modules share one `app` (and so one database), because app.py
        # binds the DB at import. Another module may have dropped the tables in its
        # teardown, so recreate them before touching anything — otherwise this
        # module passes alone and blows up in a full-suite run.
        db.create_all()
        # Curățăm tot ce a creat seed-ul de la import (săptămâna reală).
        MenuOption.query.delete()
        Selection.query.delete()
        Menu.query.delete()
        User.query.delete()
        db.session.commit()

        self.user = User(telegram_id=1001, first_name="Ion", last_name="Popescu")
        db.session.add(self.user)
        db.session.commit()

        # Ziua e fixată în ambele module: scheduler.today_md și app.today_moldova
        # (pe care se bazează app.get_week_start).
        self._patchers = [
            patch.object(sched, "today_md", return_value=self.today),
            patch.object(app_module, "today_moldova", return_value=self.today),
        ]
        for p in self._patchers:
            p.start()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        db.session.rollback()
        MenuOption.query.delete()
        Selection.query.delete()
        Menu.query.delete()
        User.query.delete()
        db.session.commit()
        self.ctx.pop()

    # Ajutoare ────────────────────────────────────────────────
    def add_selection(self, d):
        sel = Selection(user_id=self.user.id, date=d, fel_selectat=FelSelectat.felul1)
        db.session.add(sel)
        db.session.commit()
        return sel

    def add_menu(self, week_start, dow, approved=True, restaurant=Restaurant.sezatoare):
        menu = Menu(
            name="Lunch 1", day_of_week=dow, week_start_date=week_start,
            restaurant=restaurant, is_approved=approved,
        )
        db.session.add(menu)
        db.session.commit()
        return menu


# ── today_md ──────────────────────────────────────────────────

class TestTodayMd(unittest.TestCase):

    def test_today_md_uses_moldova_timezone(self):
        # 2026-03-03 22:30 UTC = 2026-03-04 00:30 la Chișinău
        with patch.object(sched, "datetime") as dt:
            dt.now.return_value = datetime(2026, 3, 4, 0, 30, tzinfo=sched.MOLDOVA_TZ)
            result = sched.today_md()
        dt.now.assert_called_once_with(sched.MOLDOVA_TZ)
        self.assertEqual(result, date(2026, 3, 4))

    def test_moldova_tz_is_chisinau(self):
        self.assertEqual(str(sched.MOLDOVA_TZ), "Europe/Chisinau")


# ── cleanup_previous_week ─────────────────────────────────────

class TestCleanupPreviousWeek(SchedulerTestCase):

    def test_deletes_last_week_keeps_this_week(self):
        last_mon = self.add_selection(PREV_MONDAY)
        last_fri = self.add_selection(PREV_MONDAY + timedelta(days=4))
        this_mon = self.add_selection(MONDAY)
        this_wed = self.add_selection(WEDNESDAY)

        sched.cleanup_previous_week(self.app, db)

        remaining = {s.date for s in Selection.query.all()}
        self.assertEqual(remaining, {MONDAY, WEDNESDAY})
        self.assertEqual(Selection.query.count(), 2)
        del last_mon, last_fri, this_mon, this_wed

    def test_does_not_touch_the_week_before_last(self):
        older = PREV_MONDAY - timedelta(days=7)
        self.add_selection(older)
        self.add_selection(PREV_MONDAY)

        sched.cleanup_previous_week(self.app, db)

        remaining = [s.date for s in Selection.query.all()]
        self.assertEqual(remaining, [older])

    def test_last_weekend_days_are_not_in_the_monfri_range(self):
        # Sâmbăta trecută (last_monday + 5) e în afara ferestrei Luni–Vineri.
        last_saturday = PREV_MONDAY + timedelta(days=5)
        self.add_selection(last_saturday)
        sched.cleanup_previous_week(self.app, db)
        self.assertEqual(Selection.query.count(), 1)

    def test_no_selections_is_a_no_op(self):
        sched.cleanup_previous_week(self.app, db)
        self.assertEqual(Selection.query.count(), 0)


class TestCleanupPreviousWeekOnFriday(SchedulerTestCase):
    """Jobul rulează vineri 23:59 — tot săptămâna TRECUTĂ trebuie ștearsă."""

    today = FRIDAY

    def test_friday_run_keeps_this_weeks_selections(self):
        self.add_selection(PREV_MONDAY + timedelta(days=2))
        self.add_selection(FRIDAY)

        sched.cleanup_previous_week(self.app, db)

        remaining = [s.date for s in Selection.query.all()]
        self.assertEqual(remaining, [FRIDAY])


# ── unapprove_past_days ───────────────────────────────────────

class TestUnapprovePastDays(SchedulerTestCase):
    """Azi = miercuri (day_of_week = 2)."""

    today = WEDNESDAY

    def setUp(self):
        super().setUp()
        self.menus = {d: self.add_menu(MONDAY, d, approved=True) for d in range(5)}
        # meniu aprobat din altă săptămână — nu trebuie atins
        self.other_week = self.add_menu(PREV_MONDAY, 0, approved=True)

    def _approved(self):
        return {m.day_of_week for m in Menu.query.filter_by(
            week_start_date=MONDAY, is_approved=True).all()}

    def test_include_today_false_leaves_today_approved(self):
        sched.unapprove_past_days(self.app, db, include_today=False)
        self.assertEqual(self._approved(), {2, 3, 4})

    def test_include_today_true_unapproves_today_as_well(self):
        sched.unapprove_past_days(self.app, db, include_today=True)
        self.assertEqual(self._approved(), {3, 4})

    def test_default_is_include_today_false(self):
        sched.unapprove_past_days(self.app, db)
        self.assertEqual(self._approved(), {2, 3, 4})

    def test_other_weeks_are_untouched(self):
        sched.unapprove_past_days(self.app, db, include_today=True)
        db.session.refresh(self.other_week)
        self.assertTrue(self.other_week.is_approved)

    def test_running_twice_is_idempotent(self):
        sched.unapprove_past_days(self.app, db, include_today=True)
        sched.unapprove_past_days(self.app, db, include_today=True)
        self.assertEqual(self._approved(), {3, 4})


class TestUnapproveOnMonday(SchedulerTestCase):
    today = MONDAY

    def test_monday_with_include_today_false_touches_nothing(self):
        for d in range(5):
            self.add_menu(MONDAY, d, approved=True)
        sched.unapprove_past_days(self.app, db, include_today=False)
        self.assertEqual(Menu.query.filter_by(is_approved=True).count(), 5)

    def test_monday_with_include_today_true_unapproves_only_monday(self):
        for d in range(5):
            self.add_menu(MONDAY, d, approved=True)
        sched.unapprove_past_days(self.app, db, include_today=True)
        approved = {m.day_of_week for m in Menu.query.filter_by(is_approved=True).all()}
        self.assertEqual(approved, {1, 2, 3, 4})


class TestUnapproveOnWeekend(SchedulerTestCase):
    today = SATURDAY

    def test_weekend_unapproves_the_whole_week(self):
        for d in range(5):
            self.add_menu(MONDAY, d, approved=True)
        sched.unapprove_past_days(self.app, db)
        self.assertEqual(Menu.query.filter_by(is_approved=True).count(), 0)

    def test_weekend_does_not_touch_other_weeks(self):
        self.add_menu(PREV_MONDAY, 0, approved=True)
        for d in range(5):
            self.add_menu(MONDAY, d, approved=True)
        sched.unapprove_past_days(self.app, db, include_today=True)
        still = Menu.query.filter_by(is_approved=True).all()
        self.assertEqual([m.week_start_date for m in still], [PREV_MONDAY])


# ── seed_weekly_menus ─────────────────────────────────────────

class TestSeedWeeklyMenus(SchedulerTestCase):
    today = WEDNESDAY

    def test_creates_the_weeks_menus_for_all_five_days(self):
        sched.seed_weekly_menus(self.app, db)
        menus = Menu.query.filter_by(week_start_date=MONDAY).all()
        self.assertEqual({m.day_of_week for m in menus}, {0, 1, 2, 3, 4})
        self.assertTrue(all(not m.is_approved for m in menus))

    def test_creates_andys_business_lunch_with_three_options(self):
        sched.seed_weekly_menus(self.app, db)
        andys = Menu.query.filter_by(
            week_start_date=MONDAY, restaurant=Restaurant.andys).all()
        self.assertEqual(len(andys), 5)  # câte unul pe zi, Luni–Vineri
        for m in andys:
            self.assertEqual(m.name, "Business Lunch 1")
            self.assertEqual(len(m.options), app_module.ANDYS_DEFAULT_OPTIONS)
            self.assertEqual(len(m.options), 3)
            self.assertEqual([o.sort_order for o in m.options], [0, 1, 2])

    def test_creates_sezatoare_menus(self):
        sched.seed_weekly_menus(self.app, db)
        sez = Menu.query.filter_by(
            week_start_date=MONDAY, restaurant=Restaurant.sezatoare).all()
        self.assertEqual(len(sez), 10)  # Lunch 1 + Lunch 2 × 5 zile
        self.assertEqual({m.name for m in sez}, {"Lunch 1", "Lunch 2"})

    def test_is_idempotent(self):
        sched.seed_weekly_menus(self.app, db)
        first = Menu.query.count()
        options_first = MenuOption.query.count()

        sched.seed_weekly_menus(self.app, db)

        self.assertEqual(Menu.query.count(), first)
        self.assertEqual(MenuOption.query.count(), options_first)

    def test_backfills_andys_on_a_week_that_only_has_sezatoare(self):
        # bază veche: săptămâna există, dar fără Andy's
        for d in range(5):
            self.add_menu(MONDAY, d, approved=False, restaurant=Restaurant.sezatoare)

        sched.seed_weekly_menus(self.app, db)

        andys = Menu.query.filter_by(
            week_start_date=MONDAY, restaurant=Restaurant.andys).all()
        self.assertEqual(len(andys), 5)
        self.assertTrue(all(len(m.options) == 3 for m in andys))
        # nu a duplicat Șezătoarea
        sez = Menu.query.filter_by(
            week_start_date=MONDAY, restaurant=Restaurant.sezatoare).count()
        self.assertEqual(sez, 5)


# ── init_scheduler ────────────────────────────────────────────

class TestInitScheduler(SchedulerTestCase):
    today = WEDNESDAY

    def tearDown(self):
        if sched.scheduler.running:
            sched.scheduler.shutdown(wait=False)
        sched.scheduler.remove_all_jobs()
        super().tearDown()

    def test_registers_exactly_four_jobs_with_the_expected_ids(self):
        sched.init_scheduler(self.app, db)
        jobs = {j.id: j for j in sched.scheduler.get_jobs()}
        self.assertEqual(
            set(jobs),
            {"weekly_cleanup_friday", "weekly_cleanup_monday",
             "weekly_seed_menus", "unapprove_daily"},
        )
        self.assertEqual(len(jobs), 4)
        self.assertTrue(sched.scheduler.running)

    def test_job_callables_and_cron_fields(self):
        sched.init_scheduler(self.app, db)
        jobs = {j.id: j for j in sched.scheduler.get_jobs()}

        self.assertIs(jobs["weekly_cleanup_friday"].func, sched.cleanup_previous_week)
        self.assertIs(jobs["weekly_cleanup_monday"].func, sched.cleanup_previous_week)
        self.assertIs(jobs["weekly_seed_menus"].func, sched.seed_weekly_menus)
        self.assertIs(jobs["unapprove_daily"].func, sched.unapprove_past_days)

        fields = {f.name: str(f) for f in jobs["weekly_cleanup_friday"].trigger.fields}
        self.assertEqual(fields["day_of_week"], "fri")
        self.assertEqual(fields["hour"], "23")
        self.assertEqual(fields["minute"], "59")

        daily = {f.name: str(f) for f in jobs["unapprove_daily"].trigger.fields}
        self.assertEqual(daily["hour"], "23")
        self.assertEqual(daily["minute"], "30")
        self.assertEqual(jobs["unapprove_daily"].kwargs, {"include_today": True})

    def test_scheduler_timezone_is_moldova(self):
        self.assertEqual(str(sched.scheduler.timezone), "Europe/Chisinau")

    def test_runs_seed_and_unapprove_once_at_startup(self):
        with patch.object(sched, "seed_weekly_menus") as seed, \
                patch.object(sched, "unapprove_past_days") as unapprove:
            sched.init_scheduler(self.app, db)
        seed.assert_called_once_with(self.app, db)
        unapprove.assert_called_once_with(self.app, db, include_today=False)

    def test_startup_seed_actually_creates_the_week(self):
        self.assertEqual(Menu.query.count(), 0)
        sched.init_scheduler(self.app, db)
        self.assertEqual(Menu.query.filter_by(week_start_date=MONDAY).count(), 15)

    def test_replace_existing_means_a_second_init_does_not_duplicate(self):
        sched.init_scheduler(self.app, db)
        sched.scheduler.shutdown(wait=False)
        sched.init_scheduler(self.app, db)
        self.assertEqual(len(sched.scheduler.get_jobs()), 4)


# ── joburile pot fi apelate cu semnătura folosită de APScheduler ──

class TestJobArgs(SchedulerTestCase):

    def test_jobs_run_end_to_end_on_a_clean_database(self):
        sched.cleanup_previous_week(self.app, db)
        sched.seed_weekly_menus(self.app, db)
        sched.unapprove_past_days(self.app, db, include_today=True)
        self.assertEqual(Menu.query.filter_by(week_start_date=MONDAY).count(), 15)
        self.assertEqual(Menu.query.filter_by(is_approved=True).count(), 0)


if __name__ == "__main__":
    unittest.main()
