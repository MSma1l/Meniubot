"""Teste unitare pentru backend/app.py — toate cele 46 de rute + căile de eroare.

Rulează în proces, cu `app.test_client()`, pe o bază SQLite temporară.
Ziua e fixată la vineri 2026-07-10 (altfel rutele „today" întorc [] în weekend),
iar `send_telegram_message` e înlocuit cu un dublu care înregistrează destinatarii.

    python -m unittest test_api -v
"""
import datetime
import hashlib
import hmac
import importlib.util
import io
import json
import os
import tempfile
import time
import unittest
from urllib.parse import urlencode

# ── Mediul TREBUIE setat înainte de `import app` ──────────────
# app.py ridică RuntimeError la import fără SECRET_KEY / INTERNAL_API_TOKEN și tot
# la import rulează db.create_all(), migrațiile și seed-ul.
_fd, _DB_PATH = tempfile.mkstemp(prefix="meniubot-test-", suffix=".db")
os.close(_fd)
os.unlink(_DB_PATH)  # SQLAlchemy o creează singur — vrem o bază curată

BOT_TOKEN = "test-bot-token"
INTERNAL_TOKEN = "test-internal"
ADMIN_USER = "admin"
ADMIN_PASS = "admin"

os.environ.setdefault("SECRET_KEY", "0" * 32)
os.environ.setdefault("INTERNAL_API_TOKEN", INTERNAL_TOKEN)
os.environ.setdefault("TELEGRAM_BOT_TOKEN", BOT_TOKEN)
os.environ.setdefault("ADMIN_USERNAME", ADMIN_USER)
os.environ.setdefault("ADMIN_PASSWORD", ADMIN_PASS)
os.environ["DATABASE_URL"] = "sqlite:///" + _DB_PATH

import jwt  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app as A  # noqa: E402
from models import (  # noqa: E402
    db, User, Menu, MenuOption, Selection, NotificationLog, Attendance,
    DailySettings, BotControl, Instruction, Restaurant, FelSelectat, NotificationType,
)

# Vineri. Săptămâna ei începe luni, 2026-07-06.
FAKE_TODAY = datetime.date(2026, 7, 10)
WEEK_START = datetime.date(2026, 7, 6)
DOW = 4  # vineri

_REAL_SEND = A.send_telegram_message
_REAL_NOW = A.now_moldova
A.today_moldova = lambda: FAKE_TODAY
A.now_moldova = lambda: datetime.datetime(2026, 7, 10, 12, 0, tzinfo=A.MOLDOVA_TZ)

APP_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.py")
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def make_init_data(telegram_id, first_name="Test", bot_token=BOT_TOKEN, auth_date=None):
    """initData semnat exact ca Telegram WebApp."""
    pairs = {
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": first_name}),
    }
    dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)


class BaseCase(unittest.TestCase):
    """Bază curată + client autentificat + Telegram simulat, pentru fiecare test."""

    def setUp(self):
        self.ctx = A.app.app_context()
        self.ctx.push()
        db.drop_all()
        db.create_all()
        A.seed_default_menus()
        db.session.add(BotControl(id=1, is_enabled=True))
        db.session.commit()

        self.sent = []          # [(chat_id, text)] — cine a primit, nu doar câți
        self.uploaded = []      # fișiere scrise în static/uploads, de curățat
        A.send_telegram_message = self._fake_send

        self.client = A.app.test_client()
        r = self.client.post("/api/auth/login",
                             json={"username": ADMIN_USER, "password": ADMIN_PASS})
        self.assertEqual(r.status_code, 200)
        self.auth = {"Authorization": "Bearer " + r.get_json()["token"]}
        self.internal = {"X-Internal-Token": INTERNAL_TOKEN}

        menus = (Menu.query.filter_by(week_start_date=WEEK_START, day_of_week=DOW)
                 .order_by(Menu.restaurant, Menu.sort_order).all())
        sez = [m for m in menus if m.restaurant == Restaurant.sezatoare]
        andys = [m for m in menus if m.restaurant == Restaurant.andys]
        self.sez1_id, self.sez2_id = sez[0].id, sez[1].id
        self.andys_id = andys[0].id
        self.option_ids = [o.id for o in andys[0].options]

    def tearDown(self):
        A.send_telegram_message = _REAL_SEND
        for fn in self.uploaded:
            p = os.path.join(A.UPLOAD_FOLDER, fn)
            if os.path.exists(p):
                os.remove(p)
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # ── dubluri și ajutoare ───────────────────────────────────

    def _fake_send(self, chat_id, text):
        # Ca originalul: stopul de urgență blochează orice mesaj.
        if not A.is_bot_enabled():
            return False
        self.sent.append((chat_id, text))
        return True

    @property
    def recipients(self):
        return [c for c, _ in self.sent]

    def tg(self, telegram_id, name="Test", bot_token=BOT_TOKEN):
        return {"X-Telegram-Init-Data": make_init_data(telegram_id, name, bot_token)}

    def mk_user(self, telegram_id, first_name="Ion", last_name="Popa",
                language="ro", is_active=True):
        u = User(telegram_id=telegram_id, first_name=first_name, last_name=last_name,
                 language=language, is_active=is_active, username="x")
        db.session.add(u)
        db.session.commit()
        return u.id

    def fill_menus(self):
        """Texte reale pe meniurile de azi + opțiunile Andy's."""
        s1 = db.session.get(Menu, self.sez1_id)
        s1.felul_1, s1.felul_2 = "Zeamă de găină", "Friptură de porc"
        s1.felul_1_ru, s1.felul_2_ru = "Куриный суп", "Свинина"
        s2 = db.session.get(Menu, self.sez2_id)
        s2.felul_1, s2.felul_2 = "Borș roșu", "Pilaf cu carne"
        a = db.session.get(Menu, self.andys_id)
        a.felul_2, a.felul_2_ru = "Pilaf de casă", "Плов"
        for i, oid in enumerate(self.option_ids):
            o = db.session.get(MenuOption, oid)
            o.text, o.text_ru = f"Supa {i}", f"Суп {i}"
        db.session.commit()

    def approve_today(self):
        for m in Menu.query.filter_by(week_start_date=WEEK_START, day_of_week=DOW).all():
            m.is_approved = True
        db.session.commit()

    def fresh(self):
        db.session.expire_all()

    def sel_of(self, user_id):
        self.fresh()
        return Selection.query.filter_by(user_id=user_id, date=FAKE_TODAY).first()


# ══ Autentificare admin ═══════════════════════════════════════

class AuthTest(BaseCase):
    def test_login_ok(self):
        r = self.client.post("/api/auth/login",
                             json={"username": ADMIN_USER, "password": ADMIN_PASS})
        self.assertEqual(r.status_code, 200)
        self.assertIn("token", r.get_json())

    def test_login_wrong_password(self):
        r = self.client.post("/api/auth/login",
                             json={"username": ADMIN_USER, "password": "nope"})
        self.assertEqual(r.status_code, 401)

    def test_login_wrong_username(self):
        r = self.client.post("/api/auth/login",
                             json={"username": "root", "password": ADMIN_PASS})
        self.assertEqual(r.status_code, 401)

    def test_login_empty_body(self):
        r = self.client.post("/api/auth/login")
        self.assertEqual(r.status_code, 401)

    def test_login_numeric_username_not_500(self):
        r = self.client.post("/api/auth/login", json={"username": 123, "password": 456})
        self.assertEqual(r.status_code, 401)

    def test_token_missing(self):
        self.assertEqual(self.client.get("/api/menus").status_code, 401)

    def test_token_invalid(self):
        r = self.client.get("/api/menus", headers={"Authorization": "Bearer garbage"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"], "Invalid token")

    def test_token_wrong_scheme(self):
        r = self.client.get("/api/menus", headers={"Authorization": "Basic abc"})
        self.assertEqual(r.status_code, 401)

    def test_token_expired(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        expired = jwt.encode(
            {"sub": ADMIN_USER, "iat": now - datetime.timedelta(hours=48),
             "exp": now - datetime.timedelta(hours=1)},
            A.app.config["SECRET_KEY"], algorithm="HS256")
        r = self.client.get("/api/menus", headers={"Authorization": f"Bearer {expired}"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error"], "Token expired")


# ══ Meniuri ═══════════════════════════════════════════════════

class MenuTest(BaseCase):
    def test_list_all(self):
        r = self.client.get("/api/menus", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()), 15)  # 5 zile × (2 sez + 1 andys)

    def test_list_filtered(self):
        r = self.client.get(f"/api/menus?restaurant=sezatoare&day_of_week={DOW}",
                            headers=self.auth)
        data = r.get_json()
        self.assertEqual(len(data), 2)
        self.assertTrue(all(m["restaurant"] == "sezatoare" for m in data))
        self.assertTrue(all(m["options"] == [] for m in data))

    def test_list_andys_has_options(self):
        r = self.client.get(f"/api/menus?restaurant=andys&day_of_week={DOW}",
                            headers=self.auth)
        data = r.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(len(data[0]["options"]), 3)

    def test_list_week_start_param(self):
        r = self.client.get(f"/api/menus?week_start={WEEK_START.isoformat()}",
                            headers=self.auth)
        self.assertEqual(len(r.get_json()), 15)
        r = self.client.get("/api/menus?week_start=2020-01-06", headers=self.auth)
        self.assertEqual(r.get_json(), [])

    def test_list_invalid_restaurant(self):
        r = self.client.get("/api/menus?restaurant=pizzeria", headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertIn("pizzeria", r.get_json()["error"])

    def test_today(self):
        r = self.client.get("/api/menus/today", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.get_json()), 3)

    def test_today_weekend_returns_empty(self):
        A.today_moldova = lambda: datetime.date(2026, 7, 11)  # sâmbătă
        try:
            self.assertEqual(self.client.get("/api/menus/today", headers=self.auth).get_json(), [])
            self.assertEqual(self.client.get("/api/menus/today/approved").get_json(), [])
        finally:
            A.today_moldova = lambda: FAKE_TODAY

    def test_today_approved(self):
        self.assertEqual(self.client.get("/api/menus/today/approved").get_json(), [])
        self.approve_today()
        data = self.client.get("/api/menus/today/approved").get_json()
        self.assertEqual(len(data), 3)
        data = self.client.get("/api/menus/today/approved?restaurant=andys").get_json()
        self.assertEqual([m["restaurant"] for m in data], ["andys"])
        r = self.client.get("/api/menus/today/approved?restaurant=x")
        self.assertEqual(r.status_code, 400)

    def test_create_sezatoare_default(self):
        r = self.client.post("/api/menus", headers=self.auth,
                             json={"name": "Dieta", "day_of_week": DOW, "felul_1": "Supă"})
        self.assertEqual(r.status_code, 201)
        m = r.get_json()
        self.assertEqual(m["restaurant"], "sezatoare")
        self.assertEqual(m["options"], [])
        self.assertEqual(m["week_start_date"], WEEK_START.isoformat())

    def test_create_andys_gets_three_options(self):
        r = self.client.post("/api/menus", headers=self.auth, json={
            "name": "Business Lunch 2", "day_of_week": DOW, "restaurant": "andys",
            "sort_order": 1, "name_ru": "БЛ2", "garnitura": "salată",
            "garnitura_ru": "салат", "felul_1_ru": "x", "felul_2_ru": "y",
            "is_approved": True, "week_start_date": WEEK_START.isoformat()})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(len(r.get_json()["options"]), A.ANDYS_DEFAULT_OPTIONS)
        self.assertTrue(r.get_json()["is_approved"])

    def test_create_missing_fields(self):
        r = self.client.post("/api/menus", headers=self.auth, json={"name": "X"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/menus", headers=self.auth)
        self.assertEqual(r.status_code, 400)

    def test_create_invalid_restaurant(self):
        r = self.client.post("/api/menus", headers=self.auth,
                             json={"name": "X", "day_of_week": 0, "restaurant": "kfc"})
        self.assertEqual(r.status_code, 400)

    def test_update_all_fields(self):
        r = self.client.put(f"/api/menus/{self.sez1_id}", headers=self.auth, json={
            "name": "Lunch A", "felul_1": "f1", "felul_2": "f2", "name_ru": "Обед A",
            "felul_1_ru": "f1ru", "felul_2_ru": "f2ru", "garnitura": "g",
            "garnitura_ru": "gru", "is_approved": True, "day_of_week": 3,
            "week_start_date": WEEK_START.isoformat()})
        self.assertEqual(r.status_code, 200)
        m = r.get_json()
        self.assertEqual(m["name"], "Lunch A")
        self.assertEqual(m["day_of_week"], 3)
        self.assertTrue(m["is_approved"])

    def test_update_missing_menu(self):
        r = self.client.put("/api/menus/99999", headers=self.auth, json={"name": "x"})
        self.assertEqual(r.status_code, 404)

    def test_approve_single(self):
        r = self.client.post(f"/api/menus/{self.sez1_id}/approve", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["is_approved"])
        self.assertEqual(self.client.post("/api/menus/0/approve", headers=self.auth).status_code, 404)

    def test_delete_menu_cleans_selections_via_all_fks(self):
        self.fill_menus()
        self.approve_today()
        uid_a = self.mk_user(1001)
        uid_b = self.mk_user(1002)
        uid_c = self.mk_user(1003)
        # a: felul1 din sez1; b: felul2 din sez1; c: Andy's (menu + option)
        db.session.add(Selection(user_id=uid_a, date=FAKE_TODAY, fel_selectat=FelSelectat.felul1,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                                 felul1_menu_id=self.sez1_id))
        db.session.add(Selection(user_id=uid_b, date=FAKE_TODAY, fel_selectat=FelSelectat.felul2,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                                 felul2_menu_id=self.sez1_id))
        db.session.add(Selection(user_id=uid_c, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                                 restaurant=Restaurant.andys, menu_id=self.andys_id,
                                 felul1_menu_id=self.andys_id, felul2_menu_id=self.andys_id,
                                 felul1_option_id=self.option_ids[0]))
        db.session.commit()

        r = self.client.delete(f"/api/menus/{self.sez1_id}", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.fresh()
        self.assertEqual(Selection.query.count(), 1)  # doar cea de la Andy's a rămas

        r = self.client.delete(f"/api/menus/{self.andys_id}", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.fresh()
        self.assertEqual(Selection.query.count(), 0)
        self.assertEqual(MenuOption.query.filter_by(menu_id=self.andys_id).count(), 0)

    def test_delete_missing_menu(self):
        self.assertEqual(self.client.delete("/api/menus/424242", headers=self.auth).status_code, 404)

    def test_reset_content(self):
        self.fill_menus()
        self.approve_today()
        r = self.client.post("/api/menus/reset-content", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["reset"], 15)
        self.assertEqual(body["options_reset"], 15)  # 5 zile × 3 opțiuni Andy's
        self.fresh()
        m = db.session.get(Menu, self.sez1_id)
        self.assertEqual((m.felul_1, m.felul_2, m.garnitura), ("", "", ""))
        self.assertFalse(m.is_approved)
        self.assertTrue(all(o.text == "" for o in db.session.get(Menu, self.andys_id).options))

    def test_approve_today_per_restaurant_and_notifications(self):
        self.mk_user(2001, language="ro")
        self.mk_user(2002, language="ru")
        r = self.client.post("/api/menus/approve-today", headers=self.auth,
                             json={"restaurant": "sezatoare"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"approved": 2, "notified": 2})
        self.assertEqual(sorted(self.recipients), [2001, 2002])
        self.assertIn("La Șezătoare", self.sent[0][1])
        self.assertIn("La Șezătoare", self.sent[1][1])  # varianta RU
        self.assertTrue(self.sent[1][1].startswith("🍽 Меню"))

    def test_approve_today_all_and_skips(self):
        uid1 = self.mk_user(2001)                      # alege → nu primește
        uid2 = self.mk_user(2002)                      # absent → nu primește
        self.mk_user(2003, is_active=False)            # inactiv → nu primește
        uid4 = self.mk_user(2004)                      # primește
        db.session.add(Selection(user_id=uid1, date=FAKE_TODAY,
                                 fel_selectat=FelSelectat.fara_pranz,
                                 restaurant=Restaurant.sezatoare))
        db.session.add(Attendance(user_id=uid2, date=FAKE_TODAY, is_present=False))
        db.session.commit()

        r = self.client.post("/api/menus/approve-today", headers=self.auth)
        self.assertEqual(r.get_json(), {"approved": 3, "notified": 1})
        self.assertEqual(self.recipients, [2004])
        self.assertIn("La Șezătoare și Andy's", self.sent[0][1])
        self.fresh()
        self.assertFalse(BotControl.query.get(1).update_required)
        self.assertEqual(db.session.get(User, uid4).telegram_id, 2004)

    def test_approve_today_invalid_restaurant(self):
        r = self.client.post("/api/menus/approve-today", headers=self.auth,
                             json={"restaurant": "kfc"})
        self.assertEqual(r.status_code, 400)

    def test_approve_today_no_menus_no_notify(self):
        Menu.query.delete()
        db.session.commit()
        self.mk_user(2001)
        r = self.client.post("/api/menus/approve-today", headers=self.auth)
        self.assertEqual(r.get_json(), {"approved": 0, "notified": 0})
        self.assertEqual(self.sent, [])


# ══ Opțiuni Andy's ════════════════════════════════════════════

class MenuOptionTest(BaseCase):
    def test_create_option_default_sort(self):
        r = self.client.post(f"/api/menus/{self.andys_id}/options", headers=self.auth,
                             json={"text": "Ciorbă", "text_ru": "Борщ"})
        self.assertEqual(r.status_code, 201)
        o = r.get_json()
        self.assertEqual(o["menu_id"], self.andys_id)
        self.assertEqual(o["sort_order"], 3)  # len(options) existente

    def test_create_option_empty_body(self):
        r = self.client.post(f"/api/menus/{self.andys_id}/options", headers=self.auth)
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["text"], "")

    def test_create_option_missing_menu(self):
        r = self.client.post("/api/menus/9999/options", headers=self.auth, json={})
        self.assertEqual(r.status_code, 404)

    def test_update_option(self):
        oid = self.option_ids[0]
        r = self.client.put(f"/api/menu-options/{oid}", headers=self.auth,
                            json={"text": "Supă", "text_ru": "Суп", "sort_order": 7})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["text"], "Supă")
        self.assertEqual(r.get_json()["sort_order"], 7)
        self.assertEqual(self.client.put("/api/menu-options/0", headers=self.auth,
                                         json={}).status_code, 404)

    def test_delete_option_cleans_selections(self):
        self.fill_menus()
        self.approve_today()
        uid = self.mk_user(3001)
        db.session.add(Selection(user_id=uid, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                                 restaurant=Restaurant.andys, menu_id=self.andys_id,
                                 felul1_menu_id=self.andys_id, felul2_menu_id=self.andys_id,
                                 felul1_option_id=self.option_ids[0]))
        db.session.commit()
        r = self.client.delete(f"/api/menu-options/{self.option_ids[0]}", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.fresh()
        self.assertEqual(Selection.query.count(), 0)
        self.assertIsNone(db.session.get(MenuOption, self.option_ids[0]))

    def test_delete_option_missing(self):
        self.assertEqual(self.client.delete("/api/menu-options/0",
                                            headers=self.auth).status_code, 404)


# ══ Selecții ══════════════════════════════════════════════════

class SelectionTest(BaseCase):
    def setUp(self):
        super().setUp()
        self.fill_menus()
        self.approve_today()
        self.uid = self.mk_user(4001, first_name="Ana")
        self.h = self.tg(4001, "Ana")

    def post_sel(self, body, headers=None):
        return self.client.post("/api/selections", headers=headers or self.h, json=body)

    def test_sezatoare_mix_two_menus(self):
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.sez1_id,
                           "felul2_menu_id": self.sez2_id, "source": "webapp"})
        self.assertEqual(r.status_code, 200)
        s = r.get_json()["selection"]
        self.assertEqual(s["fel_selectat"], "ambele")
        self.assertEqual(s["felul1_menu"]["id"], self.sez1_id)
        self.assertEqual(s["felul2_menu"]["id"], self.sez2_id)
        self.assertEqual(self.recipients, [4001])
        self.assertIn("Zeamă de găină", self.sent[0][1])
        self.assertIn("Pilaf cu carne", self.sent[0][1])

    def test_sezatoare_only_felul1(self):
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.sez1_id})
        self.assertEqual(r.get_json()["selection"]["fel_selectat"], "felul1")
        self.assertEqual(self.sent, [])  # fără source=webapp → fără mesaj

    def test_sezatoare_only_felul2(self):
        r = self.post_sel({"restaurant": "sezatoare", "felul2_menu_id": self.sez2_id})
        self.assertEqual(r.get_json()["selection"]["fel_selectat"], "felul2")
        self.assertIsNone(r.get_json()["selection"]["felul1_menu"])

    def test_andys_with_option(self):
        r = self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id,
                           "felul1_option_id": self.option_ids[1], "source": "webapp"})
        self.assertEqual(r.status_code, 200)
        s = r.get_json()["selection"]
        self.assertEqual(s["fel_selectat"], "ambele")
        self.assertEqual(s["felul1_option"]["id"], self.option_ids[1])
        self.assertEqual(s["felul2_menu"]["id"], self.andys_id)  # felul 2 fix, inclus
        self.assertIn("Supa 1", self.sent[0][1])
        self.assertIn("Pilaf de casă", self.sent[0][1])

    def test_confirmation_russian(self):
        db.session.get(User, self.uid).language = "ru"
        db.session.commit()
        self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id,
                       "felul1_option_id": self.option_ids[0], "source": "webapp"})
        body = self.sent[0][1]
        self.assertIn("Готово", body)
        self.assertIn("Суп 0", body)
        self.assertIn("Блюдо 2", body)
        self.assertIn("Бизнес Ланч 1", body)  # name_ru al meniului

    def test_confirmation_empty_dishes_shows_dash(self):
        for m in Menu.query.filter_by(week_start_date=WEEK_START, day_of_week=DOW).all():
            m.felul_1 = m.felul_2 = m.felul_1_ru = m.felul_2_ru = ""
        db.session.commit()
        self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.sez1_id,
                       "felul2_menu_id": self.sez1_id, "source": "webapp"})
        self.assertIn("—", self.sent[0][1])

    def test_fara_pranz_flag(self):
        r = self.post_sel({"fara_pranz": True, "source": "webapp"})
        self.assertEqual(r.get_json()["selection"]["fel_selectat"], "fara_pranz")
        self.assertIn("fără prânz", self.sent[0][1])

    def test_fara_pranz_via_fel_selectat(self):
        r = self.post_sel({"fel_selectat": "fara_pranz"})
        self.assertEqual(r.get_json()["selection"]["fel_selectat"], "fara_pranz")

    def test_fara_pranz_russian_text(self):
        db.session.get(User, self.uid).language = "ru"
        db.session.commit()
        self.post_sel({"fara_pranz": True, "source": "webapp"})
        self.assertIn("без обеда", self.sent[0][1])

    def test_upsert_one_order_per_day(self):
        self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.sez1_id})
        self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id,
                       "felul1_option_id": self.option_ids[0]})
        self.fresh()
        rows = Selection.query.filter_by(user_id=self.uid, date=FAKE_TODAY).all()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].restaurant, Restaurant.andys)

    # ── validări ──────────────────────────────────────────────

    def test_restaurant_required(self):
        r = self.post_sel({"felul1_menu_id": self.sez1_id})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], A.SELECTION_ERRORS["restaurant_required"])

    def test_restaurant_invalid(self):
        r = self.post_sel({"restaurant": "pizzeria", "felul1_menu_id": self.sez1_id})
        self.assertEqual(r.status_code, 400)

    def test_sezatoare_empty(self):
        r = self.post_sel({"restaurant": "sezatoare"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], A.SELECTION_ERRORS["sezatoare_empty"])

    def test_andys_without_menu(self):
        r = self.post_sel({"restaurant": "andys", "felul1_option_id": self.option_ids[0]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], A.SELECTION_ERRORS["andys_menu_required"])

    def test_andys_without_option(self):
        r = self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], A.SELECTION_ERRORS["andys_option_required"])

    def test_andys_option_does_not_exist(self):
        r = self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id,
                           "felul1_option_id": 99999})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nu aparține meniului", r.get_json()["error"])

    def test_andys_menu_not_approved(self):
        db.session.get(Menu, self.andys_id).is_approved = False
        db.session.commit()
        r = self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id,
                           "felul1_option_id": self.option_ids[0]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nu este aprobat", r.get_json()["error"])

    def test_andys_option_of_another_menu(self):
        other = self.client.post("/api/menus", headers=self.auth, json={
            "name": "BL temporar", "day_of_week": DOW, "restaurant": "andys"}).get_json()
        r = self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id,
                           "felul1_option_id": other["options"][0]["id"]})
        self.assertEqual(r.status_code, 400)

    def test_menu_missing(self):
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": 99999})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nu există", r.get_json()["error"])

    def test_menu_wrong_restaurant(self):
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.andys_id})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nu aparține restaurantului", r.get_json()["error"])

    def test_menu_not_approved(self):
        db.session.get(Menu, self.sez2_id).is_approved = False
        db.session.commit()
        r = self.post_sel({"restaurant": "sezatoare", "felul2_menu_id": self.sez2_id})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nu este aprobat", r.get_json()["error"])

    def test_menu_from_another_day(self):
        m = Menu.query.filter_by(week_start_date=WEEK_START, day_of_week=0,
                                 restaurant=Restaurant.sezatoare).first()
        m.is_approved = True
        db.session.commit()
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": m.id})
        self.assertEqual(r.status_code, 400)
        self.assertIn("nu este meniul de azi", r.get_json()["error"])

    def test_felul2_validation_also_runs(self):
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.sez1_id,
                           "felul2_menu_id": 99999})
        self.assertEqual(r.status_code, 400)

    def test_unknown_user_404(self):
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.sez1_id},
                          headers=self.tg(987654321, "Ghost"))
        self.assertEqual(r.status_code, 404)

    def test_ordering_closed_403(self):
        db.session.add(DailySettings(date=FAKE_TODAY, ordering_open=False))
        db.session.commit()
        r = self.post_sel({"restaurant": "sezatoare", "felul1_menu_id": self.sez1_id})
        self.assertEqual(r.status_code, 403)

    # ── GET /api/selections ───────────────────────────────────

    def test_get_selections_filters(self):
        self.post_sel({"restaurant": "andys", "felul1_menu_id": self.andys_id,
                       "felul1_option_id": self.option_ids[0]})
        r = self.client.get("/api/selections", headers=self.auth)
        self.assertEqual(len(r.get_json()), 1)
        r = self.client.get("/api/selections?restaurant=sezatoare", headers=self.auth)
        self.assertEqual(r.get_json(), [])
        r = self.client.get("/api/selections?date=2020-01-01", headers=self.auth)
        self.assertEqual(r.get_json(), [])
        r = self.client.get("/api/selections?restaurant=zzz", headers=self.auth)
        self.assertEqual(r.status_code, 400)

    # ── securitate Mini App ───────────────────────────────────

    def test_selection_without_init_data(self):
        r = self.client.post("/api/selections", json={"fara_pranz": True})
        self.assertEqual(r.status_code, 401)

    def test_selection_with_wrong_bot_token(self):
        r = self.post_sel({"fara_pranz": True},
                          headers=self.tg(4001, "Ana", bot_token="alt-token"))
        self.assertEqual(r.status_code, 401)

    def test_selection_with_tampered_init_data(self):
        raw = make_init_data(4001, "Ana")
        tampered = raw.replace("Ana", "Hacker")
        r = self.client.post("/api/selections", json={"fara_pranz": True},
                             headers={"X-Telegram-Init-Data": tampered})
        self.assertEqual(r.status_code, 401)

    def test_selection_with_expired_init_data(self):
        old = int(time.time()) - 48 * 3600
        r = self.post_sel({"fara_pranz": True}, headers=self.tg_old(old))
        self.assertEqual(r.status_code, 401)

    def tg_old(self, auth_date):
        return {"X-Telegram-Init-Data": make_init_data(4001, "Ana", auth_date=auth_date)}


# ══ Rapoarte ══════════════════════════════════════════════════

class ReportTest(BaseCase):
    def setUp(self):
        super().setUp()
        self.fill_menus()
        self.approve_today()

    def test_report_sezatoare(self):
        u1 = self.mk_user(5001, "Ana", "Rusu")
        u2 = self.mk_user(5002, "Ion", "Popa")
        u3 = self.mk_user(5003, "Dan", "Zota")
        db.session.add(Selection(user_id=u1, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                                 felul1_menu_id=self.sez1_id, felul2_menu_id=self.sez2_id))
        db.session.add(Selection(user_id=u2, date=FAKE_TODAY, fel_selectat=FelSelectat.felul2,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez2_id,
                                 felul2_menu_id=self.sez2_id))
        db.session.add(Selection(user_id=u3, date=FAKE_TODAY, fel_selectat=FelSelectat.fara_pranz,
                                 restaurant=Restaurant.sezatoare))
        db.session.commit()
        r = self.client.get("/api/report?restaurant=sezatoare", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["total"], 3)  # 2 porții + 1 porție; fara_pranz ignorat
        self.assertEqual(body["restaurant"], "sezatoare")
        self.assertEqual(body["date"], FAKE_TODAY.isoformat())
        self.assertIn("TOTAL PORȚII", body["report_text"])
        self.assertIn("Ana Rusu", body["report_text"])

    def test_report_sezatoare_only_felul1(self):
        u = self.mk_user(5010)
        db.session.add(Selection(user_id=u, date=FAKE_TODAY, fel_selectat=FelSelectat.felul1,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                                 felul1_menu_id=self.sez1_id))
        db.session.commit()
        body = self.client.get("/api/report?restaurant=sezatoare", headers=self.auth).get_json()
        self.assertEqual(body["total"], 1)

    def test_report_andys(self):
        u1 = self.mk_user(5004)
        u2 = self.mk_user(5005)
        for uid, opt in ((u1, self.option_ids[0]), (u2, self.option_ids[1])):
            db.session.add(Selection(user_id=uid, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                                     restaurant=Restaurant.andys, menu_id=self.andys_id,
                                     felul1_menu_id=self.andys_id, felul2_menu_id=self.andys_id,
                                     felul1_option_id=opt))
        db.session.commit()
        body = self.client.get("/api/report?restaurant=andys", headers=self.auth).get_json()
        self.assertEqual(body["total"], 2)
        self.assertIn("TOTAL COMENZI", body["report_text"])

    def test_report_andys_without_option(self):
        u = self.mk_user(5006)
        db.session.add(Selection(user_id=u, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                                 restaurant=Restaurant.andys, menu_id=self.andys_id,
                                 felul1_menu_id=self.andys_id, felul2_menu_id=self.andys_id))
        db.session.commit()
        r = self.client.get("/api/report?restaurant=andys", headers=self.auth)
        self.assertEqual(r.status_code, 200)

    def test_report_empty(self):
        body = self.client.get("/api/report?restaurant=andys", headers=self.auth).get_json()
        self.assertEqual(body["total"], 0)

    def test_report_requires_restaurant(self):
        r = self.client.get("/api/report", headers=self.auth)
        self.assertEqual(r.status_code, 400)

    def test_report_invalid_restaurant(self):
        r = self.client.get("/api/report?restaurant=kfc", headers=self.auth)
        self.assertEqual(r.status_code, 400)

    def test_report_invalid_date(self):
        r = self.client.get("/api/report?restaurant=andys&date=ieri", headers=self.auth)
        self.assertEqual(r.status_code, 400)

    def test_report_explicit_date(self):
        r = self.client.get("/api/report?restaurant=andys&date=2026-07-09", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["date"], "2026-07-09")

    def test_report_with_deleted_menus_does_not_500(self):
        """Selecții orfane (meniul șters direct din bază) → raportul nu pică (P2.2)."""
        u1 = self.mk_user(5007)
        u2 = self.mk_user(5008)
        db.session.add(Selection(user_id=u1, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                                 felul1_menu_id=self.sez1_id, felul2_menu_id=self.sez2_id))
        db.session.add(Selection(user_id=u2, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                                 restaurant=Restaurant.andys, menu_id=self.andys_id,
                                 felul1_menu_id=self.andys_id, felul2_menu_id=self.andys_id,
                                 felul1_option_id=self.option_ids[0]))
        db.session.commit()
        # ștergere brutală, fără curățarea selecțiilor
        db.session.execute(text("DELETE FROM menus WHERE id IN (:a, :b)"),
                           {"a": self.sez1_id, "b": self.andys_id})
        db.session.commit()
        self.fresh()

        r = self.client.get("/api/report?restaurant=sezatoare", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["total"], 1)  # a rămas doar felul 2
        r = self.client.get("/api/report?restaurant=andys", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["total"], 0)  # business lunch dispărut → sărit

    def test_report_person_without_user(self):
        db.session.execute(text(
            "INSERT INTO selections (user_id, date, fel_selectat, restaurant, "
            "felul1_menu_id) VALUES (99999, :d, 'felul1', 'sezatoare', :m)"),
            {"d": FAKE_TODAY, "m": self.sez1_id})
        db.session.commit()
        r = self.client.get("/api/report?restaurant=sezatoare", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertIn("?", r.get_json()["report_text"])


# ══ Notificare „mâncarea a sosit" ═════════════════════════════

class NotifyFoodArrivedTest(BaseCase):
    def setUp(self):
        super().setUp()
        self.fill_menus()
        self.approve_today()
        self.u_sez = self.mk_user(6001)                       # Șezătoare
        self.u_and = self.mk_user(6002, language="ru")        # Andy's, rusofon
        self.u_absent = self.mk_user(6003)                    # Andy's, dar absent
        self.u_inactive = self.mk_user(6004, is_active=False)  # Șezătoare, inactiv
        self.u_none = self.mk_user(6005)                      # fara_pranz
        db.session.add_all([
            Selection(user_id=self.u_sez, date=FAKE_TODAY, fel_selectat=FelSelectat.felul1,
                      restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                      felul1_menu_id=self.sez1_id),
            Selection(user_id=self.u_and, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                      restaurant=Restaurant.andys, menu_id=self.andys_id,
                      felul1_menu_id=self.andys_id, felul2_menu_id=self.andys_id,
                      felul1_option_id=self.option_ids[0]),
            Selection(user_id=self.u_absent, date=FAKE_TODAY, fel_selectat=FelSelectat.ambele,
                      restaurant=Restaurant.andys, menu_id=self.andys_id,
                      felul1_menu_id=self.andys_id, felul2_menu_id=self.andys_id,
                      felul1_option_id=self.option_ids[1]),
            Selection(user_id=self.u_inactive, date=FAKE_TODAY, fel_selectat=FelSelectat.felul2,
                      restaurant=Restaurant.sezatoare, menu_id=self.sez2_id,
                      felul2_menu_id=self.sez2_id),
            Selection(user_id=self.u_none, date=FAKE_TODAY, fel_selectat=FelSelectat.fara_pranz,
                      restaurant=Restaurant.sezatoare),
            Attendance(user_id=self.u_absent, date=FAKE_TODAY, is_present=False),
        ])
        db.session.commit()

    def test_missing_body(self):
        r = self.client.post("/api/notify/food-arrived", headers=self.auth)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], A.NOTIFY_ERRORS["scope_required"])

    def test_invalid_scope(self):
        r = self.client.post("/api/notify/food-arrived", headers=self.auth,
                             json={"restaurant": "pizzeria"})
        self.assertEqual(r.status_code, 400)

    def test_sezatoare_only(self):
        r = self.client.post("/api/notify/food-arrived", headers=self.auth,
                             json={"restaurant": "sezatoare"})
        self.assertEqual(r.get_json()["count"], 1)
        self.assertEqual(self.recipients, [6001])  # inactivul și fara_pranz sunt săriți
        self.assertIn("La Șezătoare", self.sent[0][1])
        # Doar meniurile Șezătoare sunt dez-aprobate.
        approved = self.client.get("/api/menus/today/approved").get_json()
        self.assertEqual([m["restaurant"] for m in approved], ["andys"])

    def test_andys_only_ru_and_skips_absent(self):
        r = self.client.post("/api/notify/food-arrived", headers=self.auth,
                             json={"restaurant": "andys"})
        self.assertEqual(r.get_json()["count"], 1)
        self.assertEqual(self.recipients, [6002])  # 6003 e absent
        self.assertIn("Andy's", self.sent[0][1])
        self.assertTrue(self.sent[0][1].startswith("🔔 Внимание"))
        self.fresh()
        self.assertEqual(NotificationLog.query.filter_by(
            type=NotificationType.food_arrived).count(), 1)

    def test_all(self):
        r = self.client.post("/api/notify/food-arrived", headers=self.auth,
                             json={"restaurant": "all"})
        self.assertEqual(r.get_json()["count"], 2)
        self.assertEqual(sorted(self.recipients), [6001, 6002])
        self.assertEqual(self.client.get("/api/menus/today/approved").get_json(), [])

    def test_requires_jwt(self):
        r = self.client.post("/api/notify/food-arrived", json={"restaurant": "all"})
        self.assertEqual(r.status_code, 401)

    def test_bot_stopped_sends_nothing(self):
        BotControl.query.get(1).is_enabled = False
        db.session.commit()
        r = self.client.post("/api/notify/food-arrived", headers=self.auth,
                             json={"restaurant": "all"})
        self.assertEqual(r.get_json()["count"], 0)
        self.assertEqual(self.sent, [])


# ══ Broadcast ═════════════════════════════════════════════════

class BroadcastTest(BaseCase):
    def setUp(self):
        super().setUp()
        self.ro = self.mk_user(7001, language="ro")
        self.ru = self.mk_user(7002, language="ru")
        self.off = self.mk_user(7003, language="ro", is_active=False)

    def bc(self, body):
        return self.client.post("/api/broadcast", headers=self.auth, json=body)

    def test_all_active_users(self):
        r = self.bc({"text": "Salut", "text_ru": "Привет", "target": "all"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(),
                         {"sent": 2, "failed": 0, "total": 2, "not_found": 0,
                          "bot_enabled": True})
        self.assertEqual(dict(self.sent), {7001: "Salut", 7002: "Привет"})
        self.fresh()
        self.assertEqual(NotificationLog.query.filter_by(
            type=NotificationType.broadcast).count(), 2)

    def test_russian_falls_back_to_ro_when_text_ru_empty(self):
        self.bc({"text": "Doar RO", "target": "all"})
        self.assertEqual(dict(self.sent), {7001: "Doar RO", 7002: "Doar RO"})

    def test_selected_reaches_inactive_and_dedupes(self):
        r = self.bc({"text": "Hei", "target": "selected",
                     "user_ids": [self.off, self.off, self.ro, 99999]})
        body = r.get_json()
        self.assertEqual(body["sent"], 2)
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["not_found"], 1)
        self.assertEqual(sorted(self.recipients), [7001, 7003])

    def test_text_required(self):
        self.assertEqual(self.bc({"target": "all"}).status_code, 400)
        self.assertEqual(self.bc({"text": "   ", "target": "all"}).status_code, 400)

    def test_text_too_long(self):
        r = self.bc({"text": "x" * (A.BROADCAST_MAX_LEN + 1), "target": "all"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("român", r.get_json()["error"])

    def test_text_ru_too_long(self):
        r = self.bc({"text": "ok", "text_ru": "я" * (A.BROADCAST_MAX_LEN + 1),
                     "target": "all"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("rus", r.get_json()["error"])

    def test_target_invalid(self):
        self.assertEqual(self.bc({"text": "x", "target": "nobody"}).status_code, 400)
        self.assertEqual(self.bc({"text": "x"}).status_code, 400)

    def test_user_ids_required(self):
        self.assertEqual(self.bc({"text": "x", "target": "selected"}).status_code, 400)
        self.assertEqual(self.bc({"text": "x", "target": "selected",
                                  "user_ids": []}).status_code, 400)
        self.assertEqual(self.bc({"text": "x", "target": "selected",
                                  "user_ids": "1,2"}).status_code, 400)

    def test_user_ids_must_be_numeric(self):
        r = self.bc({"text": "x", "target": "selected", "user_ids": ["abc"]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], A.BROADCAST_ERRORS["user_ids_invalid"])

    def test_user_ids_reject_booleans(self):
        r = self.bc({"text": "x", "target": "selected", "user_ids": [True, self.ro]})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], A.BROADCAST_ERRORS["user_ids_invalid"])

    def test_all_not_found_when_no_match(self):
        r = self.bc({"text": "x", "target": "selected", "user_ids": [123456]})
        self.assertEqual(r.get_json(),
                         {"sent": 0, "failed": 0, "total": 0, "not_found": 1,
                          "bot_enabled": True})

    def test_bot_stopped(self):
        BotControl.query.get(1).is_enabled = False
        db.session.commit()
        r = self.bc({"text": "x", "target": "all"})
        body = r.get_json()
        self.assertEqual(body["sent"], 0)
        self.assertEqual(body["failed"], 2)
        self.assertFalse(body["bot_enabled"])
        self.assertEqual(self.sent, [])

    def test_requires_jwt(self):
        r = self.client.post("/api/broadcast", json={"text": "x", "target": "all"})
        self.assertEqual(r.status_code, 401)


# ══ Utilizatori ═══════════════════════════════════════════════

class UserTest(BaseCase):
    def test_register_new(self):
        r = self.client.post("/api/users/register", headers=self.internal, json={
            "telegram_id": 8001, "first_name": "Ana", "last_name": "Rusu",
            "username": "ana", "language": "ru"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["language"], "ru")

    def test_register_updates_existing(self):
        self.mk_user(8002, "Vechi", "Nume")
        r = self.client.post("/api/users/register", headers=self.internal, json={
            "telegram_id": 8002, "first_name": "Nou", "username": "nou"})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["first_name"], "Nou")
        self.assertEqual(r.get_json()["username"], "nou")
        self.assertEqual(r.get_json()["last_name"], "Nume")

    def test_register_username_only_unknown_user(self):
        r = self.client.post("/api/users/register", headers=self.internal,
                             json={"telegram_id": 8003, "username": "fantoma"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"ok": True, "created": False})

    def test_register_requires_internal_token(self):
        r = self.client.post("/api/users/register",
                             json={"telegram_id": 1, "first_name": "X", "last_name": "Y"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/users/register",
                             headers={"X-Internal-Token": "gresit"},
                             json={"telegram_id": 1, "first_name": "X", "last_name": "Y"})
        self.assertEqual(r.status_code, 401)

    def test_check_user_internal(self):
        self.mk_user(8004)
        r = self.client.get("/api/users/check/8004", headers=self.internal)
        self.assertTrue(r.get_json()["registered"])
        r = self.client.get("/api/users/check/999", headers=self.internal)
        self.assertEqual(r.get_json(), {"registered": False})

    def test_check_user_own_record(self):
        self.mk_user(8005)
        r = self.client.get("/api/users/check/8005", headers=self.tg(8005))
        self.assertTrue(r.get_json()["registered"])

    def test_check_user_someone_else_403(self):
        self.mk_user(8006)
        r = self.client.get("/api/users/check/8006", headers=self.tg(8007))
        self.assertEqual(r.status_code, 403)

    def test_check_user_no_auth(self):
        self.assertEqual(self.client.get("/api/users/check/1").status_code, 401)

    def test_list_users(self):
        self.mk_user(8008)
        r = self.client.get("/api/users", headers=self.auth)
        self.assertEqual(len(r.get_json()), 1)
        self.assertEqual(self.client.get("/api/users").status_code, 401)

    def test_history(self):
        self.fill_menus()
        uid = self.mk_user(8009)
        db.session.add(Selection(user_id=uid, date=FAKE_TODAY, fel_selectat=FelSelectat.felul1,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                                 felul1_menu_id=self.sez1_id))
        db.session.add(Selection(user_id=uid, date=datetime.date(2026, 7, 9),
                                 fel_selectat=FelSelectat.fara_pranz,
                                 restaurant=Restaurant.sezatoare))
        db.session.commit()
        r = self.client.get(f"/api/users/{uid}/history", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        rows = r.get_json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["menu_felul_1"], "Zeamă de găină")  # cea mai recentă
        self.assertIsNone(rows[1]["menu_name"])                      # fara_pranz → fără meniu
        self.assertEqual(self.client.get("/api/users/0/history",
                                         headers=self.auth).status_code, 404)

    def test_update_user(self):
        uid = self.mk_user(8010)
        r = self.client.put(f"/api/users/{uid}", headers=self.auth, json={
            "first_name": "Nou", "last_name": "Nume", "language": "ru", "is_active": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["language"], "ru")
        self.assertFalse(r.get_json()["is_active"])
        self.assertEqual(self.client.put("/api/users/0", headers=self.auth,
                                         json={}).status_code, 404)

    def test_delete_user_cleans_children(self):
        """Ștergerea unui user cu rând în attendance nu mai dă 500 (P2.3)."""
        uid = self.mk_user(8011)
        db.session.add_all([
            Selection(user_id=uid, date=FAKE_TODAY, fel_selectat=FelSelectat.fara_pranz,
                      restaurant=Restaurant.sezatoare),
            Attendance(user_id=uid, date=FAKE_TODAY, is_present=False),
            NotificationLog(user_id=uid, type=NotificationType.reminder),
        ])
        db.session.commit()
        r = self.client.delete(f"/api/users/{uid}", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.fresh()
        self.assertEqual(User.query.count(), 0)
        self.assertEqual(Selection.query.count(), 0)
        self.assertEqual(Attendance.query.count(), 0)
        self.assertEqual(NotificationLog.query.count(), 0)

    def test_delete_user_missing(self):
        self.assertEqual(self.client.delete("/api/users/0", headers=self.auth).status_code, 404)


# ══ Prezență ══════════════════════════════════════════════════

class AttendanceTest(BaseCase):
    def test_get_defaults_present(self):
        uid = self.mk_user(9001, "Ana")
        self.mk_user(9002, "Zoe", is_active=False)
        r = self.client.get("/api/attendance", headers=self.auth)
        rows = r.get_json()
        self.assertEqual(len(rows), 1)  # inactivul nu apare
        self.assertEqual(rows[0]["user_id"], uid)
        self.assertTrue(rows[0]["is_present"])

    def test_post_and_toggle(self):
        uid = self.mk_user(9003)
        r = self.client.post("/api/attendance", headers=self.auth,
                             json={"user_id": uid, "is_present": False})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.client.get("/api/attendance",
                                         headers=self.auth).get_json()[0]["is_present"])
        # a doua oară actualizează rândul existent
        self.client.post("/api/attendance", headers=self.auth,
                         json={"user_id": uid, "is_present": True})
        self.fresh()
        self.assertEqual(Attendance.query.count(), 1)
        self.assertTrue(Attendance.query.first().is_present)

    def test_post_explicit_date(self):
        uid = self.mk_user(9004)
        self.client.post("/api/attendance", headers=self.auth,
                         json={"user_id": uid, "is_present": False, "date": "2026-07-08"})
        r = self.client.get("/api/attendance?date=2026-07-08", headers=self.auth)
        self.assertFalse(r.get_json()[0]["is_present"])
        r = self.client.get("/api/attendance?date=2026-07-09", headers=self.auth)
        self.assertTrue(r.get_json()[0]["is_present"])

    def test_bulk(self):
        u1 = self.mk_user(9005)
        u2 = self.mk_user(9006)
        r = self.client.post("/api/attendance/bulk", headers=self.auth, json={
            "updates": [{"user_id": u1, "is_present": False},
                        {"user_id": u2, "is_present": True}]})
        self.assertEqual(r.status_code, 200)
        # a doua rulare updatează rândurile existente + dată explicită
        r = self.client.post("/api/attendance/bulk", headers=self.auth, json={
            "date": "2026-07-10",
            "updates": [{"user_id": u1, "is_present": True}]})
        self.assertEqual(r.status_code, 200)
        self.fresh()
        self.assertEqual(Attendance.query.count(), 2)
        self.assertTrue(Attendance.query.filter_by(user_id=u1).first().is_present)

    def test_stats_default_week(self):
        uid = self.mk_user(9007)
        db.session.add(Attendance(user_id=uid, date=FAKE_TODAY, is_present=False))
        db.session.add(Attendance(user_id=uid, date=WEEK_START, is_present=True))
        db.session.commit()
        rows = self.client.get("/api/attendance/stats", headers=self.auth).get_json()
        self.assertEqual(rows[0]["total_days"], 5)
        self.assertEqual(rows[0]["days_absent"], 1)
        self.assertEqual(rows[0]["days_present"], 4)

    def test_stats_explicit_range(self):
        self.mk_user(9008)
        rows = self.client.get(
            "/api/attendance/stats?start=2026-07-06&end=2026-07-12",
            headers=self.auth).get_json()
        self.assertEqual(rows[0]["total_days"], 5)  # doar zilele lucrătoare
        self.assertEqual(rows[0]["days_absent"], 0)

    def test_requires_jwt(self):
        self.assertEqual(self.client.get("/api/attendance").status_code, 401)
        self.assertEqual(self.client.post("/api/attendance", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/attendance/bulk", json={}).status_code, 401)
        self.assertEqual(self.client.get("/api/attendance/stats").status_code, 401)


# ══ Comenzi: deschidere / închidere ═══════════════════════════

class OrderingTest(BaseCase):
    def test_status_default_open(self):
        r = self.client.get("/api/ordering/status")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ordering_open"])
        self.assertEqual(r.get_json()["date"], FAKE_TODAY.isoformat())
        self.assertTrue(self.client.get("/api/webapp/ordering-status").get_json()["ordering_open"])

    def test_close_notifies_only_users_without_selection(self):
        uid1 = self.mk_user(10001)                    # a ales → nu primește
        uid2 = self.mk_user(10002)                    # absent → nu primește
        self.mk_user(10003, is_active=False)          # inactiv → nu primește
        self.mk_user(10004, language="ru")            # primește (RU)
        self.mk_user(10005)                           # primește (RO)
        db.session.add(Selection(user_id=uid1, date=FAKE_TODAY,
                                 fel_selectat=FelSelectat.fara_pranz,
                                 restaurant=Restaurant.sezatoare))
        db.session.add(Attendance(user_id=uid2, date=FAKE_TODAY, is_present=False))
        db.session.commit()

        r = self.client.post("/api/ordering/close", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["sent_count"], 2)
        self.assertEqual(sorted(self.recipients), [10004, 10005])
        self.assertTrue(dict(self.sent)[10004].startswith("⏰ Упс"))
        self.assertIn("@CroweTM_Office", dict(self.sent)[10005])

        st = self.client.get("/api/ordering/status").get_json()
        self.assertFalse(st["ordering_open"])
        self.assertIsNotNone(st["closed_at"])
        self.assertFalse(self.client.get("/api/webapp/ordering-status").get_json()["ordering_open"])

    def test_close_twice_updates_row(self):
        self.client.post("/api/ordering/close", headers=self.auth)
        self.client.post("/api/ordering/close", headers=self.auth)
        self.fresh()
        self.assertEqual(DailySettings.query.count(), 1)

    def test_open_reopens(self):
        self.client.post("/api/ordering/close", headers=self.auth)
        r = self.client.post("/api/ordering/open", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.client.get("/api/ordering/status").get_json()["ordering_open"])

    def test_open_without_settings_row(self):
        r = self.client.post("/api/ordering/open", headers=self.auth)
        self.assertEqual(r.get_json(), {"ok": True})
        self.fresh()
        self.assertEqual(DailySettings.query.count(), 0)

    def test_requires_jwt(self):
        self.assertEqual(self.client.post("/api/ordering/close").status_code, 401)
        self.assertEqual(self.client.post("/api/ordering/open").status_code, 401)


# ══ Control bot ═══════════════════════════════════════════════

class BotControlTest(BaseCase):
    def test_status(self):
        r = self.client.get("/api/bot/status")
        self.assertTrue(r.get_json()["is_enabled"])
        self.assertEqual(r.get_json()["reminder_start"], "09:00")

    def test_status_without_row(self):
        db.session.delete(BotControl.query.get(1))
        db.session.commit()
        r = self.client.get("/api/bot/status")
        self.assertEqual(r.get_json(),
                         {"is_enabled": True, "stopped_at": None, "started_at": None})

    def test_stop_and_start(self):
        r = self.client.post("/api/bot/stop", headers=self.auth, json={"password": ADMIN_PASS})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(self.client.get("/api/bot/status").get_json()["is_enabled"])
        r = self.client.post("/api/bot/start", headers=self.auth, json={"password": ADMIN_PASS})
        self.assertEqual(r.status_code, 200)
        body = self.client.get("/api/bot/status").get_json()
        self.assertTrue(body["is_enabled"])
        self.assertIsNotNone(body["started_at"])
        self.assertIsNotNone(body["stopped_at"])

    def test_stop_wrong_password(self):
        r = self.client.post("/api/bot/stop", headers=self.auth, json={"password": "x"})
        self.assertEqual(r.status_code, 401)
        r = self.client.post("/api/bot/start", headers=self.auth, json={})
        self.assertEqual(r.status_code, 401)

    def test_stop_start_create_row_when_missing(self):
        db.session.delete(BotControl.query.get(1))
        db.session.commit()
        self.client.post("/api/bot/stop", headers=self.auth, json={"password": ADMIN_PASS})
        self.fresh()
        self.assertFalse(BotControl.query.get(1).is_enabled)
        db.session.delete(BotControl.query.get(1))
        db.session.commit()
        self.client.post("/api/bot/start", headers=self.auth, json={"password": ADMIN_PASS})
        self.fresh()
        self.assertTrue(BotControl.query.get(1).is_enabled)

    def test_settings_update(self):
        r = self.client.put("/api/bot/settings", headers=self.auth, json={
            "reminder_start": "08:30", "reminder_end": "11:00",
            "is_holiday": True, "update_required": True})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["reminder_start"], "08:30")
        self.assertTrue(r.get_json()["is_holiday"])
        self.assertTrue(r.get_json()["update_required"])

    def test_settings_create_row_when_missing(self):
        db.session.delete(BotControl.query.get(1))
        db.session.commit()
        r = self.client.put("/api/bot/settings", headers=self.auth, json={})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["is_enabled"])

    def test_requires_jwt(self):
        self.assertEqual(self.client.post("/api/bot/stop",
                                          json={"password": ADMIN_PASS}).status_code, 401)
        self.assertEqual(self.client.post("/api/bot/start",
                                          json={"password": ADMIN_PASS}).status_code, 401)
        self.assertEqual(self.client.put("/api/bot/settings", json={}).status_code, 401)


# ══ Pending users (remindere) ═════════════════════════════════

class PendingUsersTest(BaseCase):
    def setUp(self):
        super().setUp()
        self.approve_today()
        self.uid = self.mk_user(11001, language="ru")

    def pending(self):
        r = self.client.get("/api/notify/pending-users", headers=self.internal)
        self.assertEqual(r.status_code, 200)
        return r.get_json()

    def test_happy_path(self):
        self.assertEqual(self.pending(),
                         [{"telegram_id": 11001, "language": "ru"}])

    def test_requires_internal_token(self):
        self.assertEqual(self.client.get("/api/notify/pending-users").status_code, 401)

    def test_empty_when_bot_stopped(self):
        BotControl.query.get(1).is_enabled = False
        db.session.commit()
        self.assertEqual(self.pending(), [])

    def test_empty_on_holiday(self):
        BotControl.query.get(1).is_holiday = True
        db.session.commit()
        self.assertEqual(self.pending(), [])

    def test_empty_on_weekend(self):
        A.today_moldova = lambda: datetime.date(2026, 7, 11)
        try:
            self.assertEqual(self.pending(), [])
        finally:
            A.today_moldova = lambda: FAKE_TODAY

    def test_empty_when_ordering_closed(self):
        db.session.add(DailySettings(date=FAKE_TODAY, ordering_open=False))
        db.session.commit()
        self.assertEqual(self.pending(), [])

    def test_empty_when_no_approved_menu(self):
        for m in Menu.query.all():
            m.is_approved = False
        db.session.commit()
        self.assertEqual(self.pending(), [])

    def test_skips_absent_and_selected(self):
        other = self.mk_user(11002)
        db.session.add(Attendance(user_id=self.uid, date=FAKE_TODAY, is_present=False))
        db.session.add(Selection(user_id=other, date=FAKE_TODAY,
                                 fel_selectat=FelSelectat.fara_pranz,
                                 restaurant=Restaurant.sezatoare))
        db.session.commit()
        self.assertEqual(self.pending(), [])


# ══ WebApp ════════════════════════════════════════════════════

class WebAppTest(BaseCase):
    def test_serve_webapp(self):
        r = self.client.get("/webapp")
        self.assertEqual(r.status_code, 200)

    def test_my_selection_unknown_user(self):
        r = self.client.get("/api/webapp/my-selection", headers=self.tg(12001))
        self.assertEqual(r.get_json(), {"has_selection": False})

    def test_my_selection_without_selection(self):
        self.mk_user(12002)
        r = self.client.get("/api/webapp/my-selection", headers=self.tg(12002))
        self.assertEqual(r.get_json(), {"has_selection": False})

    def test_my_selection_with_selection(self):
        self.fill_menus()
        uid = self.mk_user(12003)
        db.session.add(Selection(user_id=uid, date=FAKE_TODAY, fel_selectat=FelSelectat.felul1,
                                 restaurant=Restaurant.sezatoare, menu_id=self.sez1_id,
                                 felul1_menu_id=self.sez1_id))
        db.session.commit()
        r = self.client.get("/api/webapp/my-selection", headers=self.tg(12003))
        self.assertEqual(r.get_json(),
                         {"has_selection": True, "fel_selectat": "felul1",
                          "menu_name": "Lunch 1"})

    def test_my_selection_requires_init_data(self):
        self.assertEqual(self.client.get("/api/webapp/my-selection").status_code, 401)


# ══ Instrucțiuni ══════════════════════════════════════════════

class InstructionTest(BaseCase):
    def mk_instruction(self, with_image=True, filename="poza.png"):
        data = {"title": "Pas 1", "title_ru": "Шаг 1", "content": "text",
                "content_ru": "текст", "sort_order": "2"}
        if with_image:
            data["image"] = (io.BytesIO(PNG_BYTES), filename)
        r = self.client.post("/api/instructions", headers=self.auth, data=data,
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        if body["image_filename"]:
            self.uploaded.append(body["image_filename"])
        return body

    def test_create_with_image(self):
        body = self.mk_instruction()
        self.assertEqual(body["title"], "Pas 1")
        self.assertEqual(body["sort_order"], 2)
        self.assertTrue(body["image_filename"].endswith(".png"))
        self.assertTrue(os.path.exists(os.path.join(A.UPLOAD_FOLDER, body["image_filename"])))

    def test_create_without_image(self):
        body = self.mk_instruction(with_image=False)
        self.assertEqual(body["image_filename"], "")

    def test_create_rejects_bad_extension(self):
        body = self.mk_instruction(filename="virus.exe")
        self.assertEqual(body["image_filename"], "")

    def test_create_ignores_empty_filename(self):
        r = self.client.post("/api/instructions", headers=self.auth,
                             data={"title": "T", "image": (io.BytesIO(b""), "")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["image_filename"], "")

    def test_public_list_only_active(self):
        a = self.mk_instruction(with_image=False)
        db.session.get(Instruction, a["id"]).is_active = False
        db.session.commit()
        self.assertEqual(self.client.get("/api/instructions").get_json(), [])
        r = self.client.get("/api/instructions/all", headers=self.auth)
        self.assertEqual(len(r.get_json()), 1)
        self.assertEqual(self.client.get("/api/instructions/all").status_code, 401)

    def test_update_json(self):
        a = self.mk_instruction(with_image=False)
        r = self.client.put(f"/api/instructions/{a['id']}", headers=self.auth, json={
            "title": "Nou", "title_ru": "Новый", "content": "c", "content_ru": "с",
            "sort_order": 9, "is_active": False})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["title"], "Nou")
        self.assertEqual(r.get_json()["sort_order"], 9)
        self.assertFalse(r.get_json()["is_active"])

    def test_update_multipart_replaces_image(self):
        a = self.mk_instruction()
        old = a["image_filename"]
        r = self.client.put(f"/api/instructions/{a['id']}", headers=self.auth, data={
            "title": "Nou", "title_ru": "Н", "content": "c", "content_ru": "с",
            "sort_order": "5", "is_active": "true",
            "image": (io.BytesIO(PNG_BYTES), "alta.jpg")},
            content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.uploaded.append(body["image_filename"])
        self.assertNotEqual(body["image_filename"], old)
        self.assertTrue(body["image_filename"].endswith(".jpg"))
        self.assertTrue(body["is_active"])
        self.assertFalse(os.path.exists(os.path.join(A.UPLOAD_FOLDER, old)))

    def test_update_multipart_without_image(self):
        a = self.mk_instruction(with_image=False)
        r = self.client.put(f"/api/instructions/{a['id']}", headers=self.auth,
                            data={"is_active": "0"}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.get_json()["is_active"])

    def test_update_missing(self):
        self.assertEqual(self.client.put("/api/instructions/0", headers=self.auth,
                                         json={}).status_code, 404)

    def test_remove_image(self):
        a = self.mk_instruction()
        path = os.path.join(A.UPLOAD_FOLDER, a["image_filename"])
        r = self.client.post(f"/api/instructions/{a['id']}/remove-image", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["image_filename"], "")
        self.assertFalse(os.path.exists(path))
        # a doua oară: nu mai are imagine → no-op
        r = self.client.post(f"/api/instructions/{a['id']}/remove-image", headers=self.auth)
        self.assertEqual(r.status_code, 200)

    def test_delete_with_image(self):
        a = self.mk_instruction()
        path = os.path.join(A.UPLOAD_FOLDER, a["image_filename"])
        r = self.client.delete(f"/api/instructions/{a['id']}", headers=self.auth)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(os.path.exists(path))
        self.fresh()
        self.assertEqual(Instruction.query.count(), 0)

    def test_delete_without_image(self):
        a = self.mk_instruction(with_image=False)
        self.assertEqual(self.client.delete(f"/api/instructions/{a['id']}",
                                            headers=self.auth).status_code, 200)
        self.assertEqual(self.client.delete("/api/instructions/0",
                                            headers=self.auth).status_code, 404)

    def test_serve_upload(self):
        a = self.mk_instruction()
        r = self.client.get(f"/api/static/uploads/{a['image_filename']}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, PNG_BYTES)
        self.assertEqual(self.client.get("/api/static/uploads/lipsa.png").status_code, 404)

    def test_requires_jwt(self):
        self.assertEqual(self.client.post("/api/instructions", data={}).status_code, 401)
        self.assertEqual(self.client.put("/api/instructions/1", json={}).status_code, 401)
        self.assertEqual(self.client.delete("/api/instructions/1").status_code, 401)
        self.assertEqual(self.client.post("/api/instructions/1/remove-image").status_code, 401)


# ══ send_telegram_message (funcția reală) ═════════════════════

class _FakeResponse:
    def __init__(self, ok=True, text=""):
        self.ok = ok
        self.text = text


class _FakeRequests:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json))
        if self.exc:
            raise self.exc
        return self.response


class SendTelegramTest(BaseCase):
    def setUp(self):
        super().setUp()
        A.send_telegram_message = _REAL_SEND  # aici testăm chiar funcția reală
        self.real_requests = A.requests
        self.real_token = A.TELEGRAM_BOT_TOKEN

    def tearDown(self):
        A.requests = self.real_requests
        A.TELEGRAM_BOT_TOKEN = self.real_token
        super().tearDown()

    def test_blocked_when_bot_stopped(self):
        BotControl.query.get(1).is_enabled = False
        db.session.commit()
        A.requests = _FakeRequests(_FakeResponse())
        self.assertFalse(A.send_telegram_message(1, "hi"))
        self.assertEqual(A.requests.calls, [])

    def test_no_token(self):
        A.TELEGRAM_BOT_TOKEN = None
        A.requests = _FakeRequests(_FakeResponse())
        self.assertFalse(A.send_telegram_message(1, "hi"))
        self.assertEqual(A.requests.calls, [])

    def test_success(self):
        A.requests = _FakeRequests(_FakeResponse(ok=True))
        self.assertTrue(A.send_telegram_message(42, "salut"))
        url, payload = A.requests.calls[0]
        self.assertIn(BOT_TOKEN, url)
        self.assertEqual(payload, {"chat_id": 42, "text": "salut"})

    def test_api_error(self):
        A.requests = _FakeRequests(_FakeResponse(ok=False, text="bad"))
        self.assertFalse(A.send_telegram_message(42, "salut"))

    def test_network_exception(self):
        A.requests = _FakeRequests(exc=RuntimeError("timeout"))
        self.assertFalse(A.send_telegram_message(42, "salut"))

    def test_is_bot_enabled_without_row(self):
        db.session.delete(BotControl.query.get(1))
        db.session.commit()
        self.assertTrue(A.is_bot_enabled())


# ══ Helperi puri ══════════════════════════════════════════════

class HelperTest(BaseCase):
    def test_now_moldova_is_timezone_aware(self):
        now = _REAL_NOW()  # funcția reală, nu dublura cu ziua fixă
        self.assertEqual(now.tzinfo, A.MOLDOVA_TZ)

    def test_get_week_start(self):
        self.assertEqual(A.get_week_start(), WEEK_START)
        self.assertEqual(A.get_week_start(datetime.date(2026, 7, 6)), WEEK_START)

    def test_parse_restaurant(self):
        self.assertEqual(A.parse_restaurant("andys"), (Restaurant.andys, None))
        self.assertEqual(A.parse_restaurant(None), (None, None))
        self.assertEqual(A.parse_restaurant(""), (None, None))
        val, err = A.parse_restaurant("", required=True)
        self.assertIsNone(val)
        self.assertTrue(err)

    def test_menu_label(self):
        self.assertEqual(A.menu_label(None, "ro"), "?")
        m = db.session.get(Menu, self.andys_id)
        self.assertEqual(A.menu_label(m, "ru"), "Бизнес Ланч 1")
        self.assertEqual(A.menu_label(m, "ro"), "Business Lunch 1")
        m.name_ru = ""
        self.assertEqual(A.menu_label(m, "ru"), "Business Lunch 1")

    def test_localized(self):
        self.assertEqual(A._localized("ro", "ru", "ru"), "ru")
        self.assertEqual(A._localized("ro", "", "ru"), "ro")
        self.assertEqual(A._localized(None, None, "ro"), "")

    def test_allowed_file(self):
        self.assertTrue(A.allowed_file("a.PNG"))
        self.assertFalse(A.allowed_file("a.exe"))
        self.assertFalse(A.allowed_file("fara-extensie"))


# ══ Seed & migrații ═══════════════════════════════════════════

class SeedTest(BaseCase):
    def wipe_menus(self):
        # SQLite reciclează rowid-urile: opțiunile orfane s-ar reatașa meniurilor noi.
        MenuOption.query.delete()
        Menu.query.delete()
        db.session.commit()

    def test_seed_is_idempotent(self):
        before = Menu.query.count()
        A.seed_default_menus()
        A.seed_default_menus()
        self.fresh()
        self.assertEqual(Menu.query.count(), before)

    def test_ensure_andys_backfills_existing_week(self):
        """O săptămână veche, fără Andy's, primește business lunch pe fiecare zi."""
        self.wipe_menus()
        for day in range(5):
            db.session.add(Menu(name="Lunch 1", day_of_week=day, sort_order=0,
                                restaurant=Restaurant.sezatoare, week_start_date=WEEK_START))
        db.session.commit()

        A.seed_default_menus()  # vede săptămâna existentă → ensure_andys_menus
        self.fresh()
        andys = Menu.query.filter_by(restaurant=Restaurant.andys,
                                     week_start_date=WEEK_START).all()
        self.assertEqual(len(andys), 5)
        self.assertTrue(all(len(m.options) == A.ANDYS_DEFAULT_OPTIONS for m in andys))
        # a doua oară nu mai creează nimic
        A.ensure_andys_menus(WEEK_START)
        self.fresh()
        self.assertEqual(Menu.query.filter_by(restaurant=Restaurant.andys).count(), 5)

    def test_seed_copies_previous_week(self):
        self.wipe_menus()
        prev = WEEK_START - datetime.timedelta(days=7)
        m = Menu(name="Lunch 1", name_ru="Обед 1", day_of_week=DOW, sort_order=0,
                 restaurant=Restaurant.sezatoare, week_start_date=prev,
                 felul_1="Supă", felul_2="Friptură", garnitura="salată",
                 felul_1_ru="Суп", felul_2_ru="Жаркое", garnitura_ru="салат",
                 is_approved=True)
        db.session.add(m)
        a = Menu(name="Business Lunch 1", day_of_week=DOW, sort_order=0,
                 restaurant=Restaurant.andys, week_start_date=prev, felul_2="Pilaf")
        a.options.append(MenuOption(text="Supa A", text_ru="Суп А", sort_order=0))
        db.session.add(a)
        db.session.commit()

        A.seed_default_menus()
        self.fresh()
        copied = Menu.query.filter_by(week_start_date=WEEK_START).all()
        self.assertEqual(len(copied), 2)  # copiate 1:1 din săptămâna precedentă
        sez = [x for x in copied if x.restaurant == Restaurant.sezatoare][0]
        self.assertEqual(sez.felul_1, "Supă")
        self.assertEqual(sez.garnitura_ru, "салат")
        self.assertFalse(sez.is_approved)  # aprobarea NU se moștenește
        friday_andys = [x for x in copied if x.restaurant == Restaurant.andys][0]
        self.assertEqual([o.text for o in friday_andys.options], ["Supa A"])
        # Săptămâna copiată are Andy's doar vineri → backfill pe celelalte 4 zile.
        A.seed_default_menus()
        self.fresh()
        self.assertEqual(Menu.query.filter_by(week_start_date=WEEK_START,
                                              restaurant=Restaurant.andys).count(), 5)


class MigrationTest(unittest.TestCase):
    """Rulează migrațiile peste o schemă veche (fără coloanele noi)."""

    def setUp(self):
        self.ctx = A.app.app_context()
        self.ctx.push()
        db.drop_all()

    def tearDown(self):
        db.session.remove()
        for t in ("users", "menus", "selections", "bot_control", "menu_options",
                  "attendance", "daily_settings", "notification_logs", "instructions"):
            db.session.execute(text(f"DROP TABLE IF EXISTS {t}"))
        db.session.commit()
        db.session.remove()
        db.create_all()
        self.ctx.pop()

    def test_migrate_legacy_schema(self):
        db.session.execute(text(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, telegram_id BIGINT, "
            "first_name VARCHAR(100), last_name VARCHAR(100), language VARCHAR(5), "
            "registered_at DATETIME, is_active BOOLEAN)"))
        db.session.execute(text(
            "CREATE TABLE menus (id INTEGER PRIMARY KEY, name VARCHAR(100), "
            "day_of_week INTEGER, felul_1 VARCHAR(255), felul_2 VARCHAR(255), "
            "is_approved BOOLEAN)"))
        db.session.execute(text(
            "CREATE TABLE selections (id INTEGER PRIMARY KEY, user_id INTEGER, "
            "menu_id INTEGER, fel_selectat VARCHAR(20), selected_at DATETIME, date DATE)"))
        db.session.execute(text(
            "CREATE TABLE bot_control (id INTEGER PRIMARY KEY, is_enabled BOOLEAN, "
            "stopped_at DATETIME, started_at DATETIME)"))
        for i, name in enumerate(["Lunch 1", "Lunch 2", "Dieta", "Post"], start=1):
            db.session.execute(
                text("INSERT INTO menus (id, name, day_of_week, is_approved) "
                     "VALUES (:i, :n, 0, 0)"), {"i": i, "n": name})
        db.session.execute(text(
            "INSERT INTO selections (id, user_id, menu_id, fel_selectat, date) "
            "VALUES (1, 1, 1, 'ambele', '2026-07-10')"))
        db.session.execute(text(
            "INSERT INTO selections (id, user_id, menu_id, fel_selectat, date) "
            "VALUES (2, 2, 2, 'felul2', '2026-07-10')"))
        db.session.execute(text("INSERT INTO bot_control (id, is_enabled) VALUES (1, 1)"))
        db.session.commit()

        A.migrate_db()
        A.migrate_bot_control()

        cols = {r[1] for r in db.session.execute(text("PRAGMA table_info(menus)"))}
        self.assertTrue({"restaurant", "week_start_date", "sort_order", "name_ru",
                         "garnitura", "garnitura_ru", "felul_1_ru",
                         "felul_2_ru"} <= cols)
        self.assertIn("username", {r[1] for r in db.session.execute(text("PRAGMA table_info(users)"))})
        bot_cols = {r[1] for r in db.session.execute(text("PRAGMA table_info(bot_control)"))}
        self.assertTrue({"reminder_start", "reminder_end", "is_holiday",
                         "update_required"} <= bot_cols)

        rows = dict(db.session.execute(text("SELECT name, name_ru FROM menus")).all())
        self.assertEqual(rows["Lunch 1"], "Обед 1")
        self.assertEqual(rows["Post"], "Пост")
        self.assertTrue(all(r[0] == "sezatoare" for r in
                            db.session.execute(text("SELECT restaurant FROM menus"))))
        self.assertTrue(all(r[0] is not None for r in
                            db.session.execute(text("SELECT week_start_date FROM menus"))))

        backfill = dict(db.session.execute(text(
            "SELECT id, felul1_menu_id FROM selections")).all())
        self.assertEqual(backfill[1], 1)   # 'ambele' → felul1 copiat din menu_id
        self.assertIsNone(backfill[2])     # 'felul2' → felul1 rămâne gol
        f2 = dict(db.session.execute(text("SELECT id, felul2_menu_id FROM selections")).all())
        self.assertEqual(f2[1], 1)
        self.assertEqual(f2[2], 2)

        # A doua rulare nu mai schimbă nimic (coloanele există deja).
        A.migrate_db()
        A.migrate_bot_control()

    def test_migrate_bot_control_without_table(self):
        db.session.execute(text("DROP TABLE IF EXISTS bot_control"))
        db.session.commit()
        A.migrate_bot_control()  # nu trebuie să crape


# ══ Configurație obligatorie la import ════════════════════════

class ConfigGuardTest(unittest.TestCase):
    """app.py refuză să pornească fără secretele necesare."""

    def _load(self, env):
        old = {k: os.environ.get(k) for k in env}
        os.environ.update({k: v for k, v in env.items() if v is not None})
        for k, v in env.items():
            if v is None:
                os.environ.pop(k, None)
        try:
            spec = importlib.util.spec_from_file_location("app_guard_probe", APP_PY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_missing_secret_key(self):
        with self.assertRaises(RuntimeError) as cm:
            self._load({"SECRET_KEY": None})
        self.assertIn("SECRET_KEY", str(cm.exception))

    def test_dangerous_secret_key(self):
        with self.assertRaises(RuntimeError):
            self._load({"SECRET_KEY": "dev-secret-key"})

    def test_missing_internal_token(self):
        with self.assertRaises(RuntimeError) as cm:
            self._load({"INTERNAL_API_TOKEN": None})
        self.assertIn("INTERNAL_API_TOKEN", str(cm.exception))


def tearDownModule():
    if os.path.exists(_DB_PATH):
        os.remove(_DB_PATH)


if __name__ == "__main__":
    unittest.main()
