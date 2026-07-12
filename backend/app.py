import hmac
import os
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import logging

import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, g
from flask_cors import CORS
import jwt

from models import (
    db, User, Menu, MenuOption, Selection, NotificationLog, FelSelectat,
    NotificationType, Restaurant, Attendance, DailySettings, BotControl, Instruction,
)
from calculations import (
    build_sezatoare_report,
    build_andys_report,
    count_sezatoare,
    count_andys,
)
from auth import require_telegram, require_internal, require_telegram_or_internal

load_dotenv()

app = Flask(__name__, static_folder="static")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///meniubot.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Fail fast: a missing or default SECRET_KEY silently breaks token security.
_secret_key = os.getenv("SECRET_KEY", "")
_DANGEROUS_SECRETS = {"dev-secret-key", "your_secret_key"}
if not _secret_key or _secret_key in _DANGEROUS_SECRETS:
    raise RuntimeError(
        "SECRET_KEY lipsește sau are o valoare periculoasă. "
        "Setează un secret unic în variabilele de mediu. "
        'Generează-l cu: python3 -c "import secrets; print(secrets.token_hex(32))"'
    )
app.config["SECRET_KEY"] = _secret_key

# Fail fast: botul are nevoie de acest secret ca să vorbească cu API-ul intern.
if not os.getenv("INTERNAL_API_TOKEN"):
    raise RuntimeError(
        "INTERNAL_API_TOKEN lipsește. E necesar pentru ca procesul bot să "
        "se autentifice la API-ul intern. "
        'Generează-l cu: python3 -c "import secrets; print(secrets.token_hex(32))"'
    )

CORS(app)
db.init_app(app)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
OFFICE_ADDRESS = os.getenv("OFFICE_ADDRESS", "str. Exemplu 123, Chișinău")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logger = logging.getLogger(__name__)

# Moldova timezone (EET/EEST — auto-adjusts for DST)
MOLDOVA_TZ = ZoneInfo("Europe/Chisinau")

def now_moldova():
    return datetime.now(MOLDOVA_TZ)

def today_moldova():
    """Get today's date in Moldova timezone."""
    return datetime.now(MOLDOVA_TZ).date()

# Localized messages
# Keyed by language, then by notified scope (restaurant or "all" for both).
FOOD_ARRIVED_TEXTS = {
    "ro": {
        "sezatoare": (
            "🔔 Atenție, prânzul de la La Șezătoare a sosit!\n\n"
            "Mâncarea vă așteaptă caldă — coborâți să serviți. 🍽\n"
            "Poftă bună și o zi cu spor! 💛"
        ),
        "andys": (
            "🔔 Atenție, prânzul de la Andy's a sosit!\n\n"
            "Mâncarea vă așteaptă caldă — coborâți să serviți. 🍽\n"
            "Poftă bună și o zi cu spor! 💛"
        ),
        "all": (
            "🔔 Atenție, prânzul a sosit!\n\n"
            "Mâncarea de la ambele restaurante vă așteaptă caldă — coborâți să serviți. 🍽\n"
            "Poftă bună și o zi cu spor! 💛"
        ),
    },
    "ru": {
        "sezatoare": (
            "🔔 Внимание, обед из La Șezătoare прибыл!\n\n"
            "Еда уже ждёт вас горячей — можете спускаться. 🍽\n"
            "Приятного аппетита и продуктивного дня! 💛"
        ),
        "andys": (
            "🔔 Внимание, обед из Andy's прибыл!\n\n"
            "Еда уже ждёт вас горячей — можете спускаться. 🍽\n"
            "Приятного аппетита и продуктивного дня! 💛"
        ),
        "all": (
            "🔔 Внимание, обед прибыл!\n\n"
            "Еда из обоих ресторанов уже ждёт вас горячей — можете спускаться. 🍽\n"
            "Приятного аппетита и продуктивного дня! 💛"
        ),
    },
}

# Errors for POST /api/notify/food-arrived (admin panel — RO only).
NOTIFY_ERRORS = {
    "scope_required": "Restaurantul este obligatoriu (sezatoare, andys sau all).",
    "scope_invalid": "Restaurant invalid: {value}",
}

# A new Andy's business lunch starts with this many empty Felul 1 options.
ANDYS_DEFAULT_OPTIONS = 3

# Scope of a food-arrived notification → the restaurants it covers.
NOTIFY_SCOPES = {
    "sezatoare": (Restaurant.sezatoare,),
    "andys": (Restaurant.andys,),
    "all": (Restaurant.sezatoare, Restaurant.andys),
}

SELECTION_CONFIRM_TEXTS = {
    "ro": (
        "✅ Gata, alegerea ta e salvată!\n\n"
        "🍽 Restaurant: {restaurant}\n"
        "{details}\n\n"
        "Îți vom da de știre imediat ce sosește mâncarea. Ziua bună! 🌤"
    ),
    "ru": (
        "✅ Готово, ваш выбор сохранён!\n\n"
        "🍽 Ресторан: {restaurant}\n"
        "{details}\n\n"
        "Сообщим, как только прибудет еда. Хорошего дня! 🌤"
    ),
}

SELECTION_NO_LUNCH_TEXTS = {
    "ro": (
        "👍 Am înțeles — azi fără prânz.\n\n"
        "Nu vă deranjăm cu notificări. Dacă vă răzgândiți, reveniți în aplicație! 😊"
    ),
    "ru": (
        "👍 Понятно — сегодня без обеда.\n\n"
        "Не будем беспокоить уведомлениями. Если передумаете, заходите в приложение! 😊"
    ),
}

# Sent to everyone who hasn't chosen yet, right after the admin approves the menu.
# Keyed by language, then by approved scope (restaurant or "all" for both).
MENU_READY_TEXTS = {
    "ro": {
        "sezatoare": (
            "🍽 Meniul de azi de la La Șezătoare e gata!\n\n"
            "Intră în aplicație și alege-ți prânzul — durează 10 secunde. ⏱\n"
            "Poftă bună la alegere! 😋"
        ),
        "andys": (
            "🍽 Meniul de azi de la Andy's e gata!\n\n"
            "Intră în aplicație și alege-ți prânzul — durează 10 secunde. ⏱\n"
            "Poftă bună la alegere! 😋"
        ),
        "all": (
            "🍽 Meniul de azi e gata — La Șezătoare și Andy's!\n\n"
            "Intră în aplicație și alege-ți prânzul — durează 10 secunde. ⏱\n"
            "Poftă bună la alegere! 😋"
        ),
    },
    "ru": {
        "sezatoare": (
            "🍽 Меню на сегодня из La Șezătoare готово!\n\n"
            "Заходите в приложение и выберите обед — это займёт 10 секунд. ⏱\n"
            "Приятного выбора! 😋"
        ),
        "andys": (
            "🍽 Меню на сегодня из Andy's готово!\n\n"
            "Заходите в приложение и выберите обед — это займёт 10 секунд. ⏱\n"
            "Приятного выбора! 😋"
        ),
        "all": (
            "🍽 Меню на сегодня готово — La Șezătoare и Andy's!\n\n"
            "Заходите в приложение и выберите обед — это займёт 10 секунд. ⏱\n"
            "Приятного выбора! 😋"
        ),
    },
}

RESTAURANT_LABELS = {
    "ro": {"sezatoare": "La Șezătoare", "andys": "Andy's"},
    "ru": {"sezatoare": "La Șezătoare", "andys": "Andy's"},
}

FEL_LABELS = {
    "ro": {"felul1": "Felul 1", "felul2": "Felul 2", "ambele": "Felul 1 + Felul 2"},
    "ru": {"felul1": "Блюдо 1", "felul2": "Блюдо 2", "ambele": "Блюдо 1 + Блюдо 2"},
}

# Validation errors returned to the Mini App (RO — the admin panel and API speak RO).
SELECTION_ERRORS = {
    "restaurant_required": "Restaurantul este obligatoriu (sezatoare sau andys).",
    "restaurant_invalid": "Restaurant invalid: {value}",
    "menu_missing": "Meniul {menu_id} nu există.",
    "menu_wrong_restaurant": "Meniul {menu_id} nu aparține restaurantului {restaurant}.",
    "menu_not_approved": "Meniul {menu_id} nu este aprobat.",
    "menu_not_today": "Meniul {menu_id} nu este meniul de azi.",
    "sezatoare_empty": "Alege cel puțin Felul 1 sau Felul 2.",
    "andys_menu_required": "Pentru Andy's trebuie ales un business lunch (felul1_menu_id).",
    "andys_option_required": "Pentru Andy's trebuie aleasă o opțiune de Felul 1 (felul1_option_id).",
    "andys_option_invalid": "Opțiunea {option_id} nu aparține meniului {menu_id}.",
}


def is_bot_enabled():
    """Check if the bot is enabled (emergency stop not active)."""
    ctrl = BotControl.query.get(1)
    return ctrl.is_enabled if ctrl else True


def send_telegram_message(chat_id, text):
    """Send a message via Telegram Bot API. Blocked when bot is stopped."""
    if not is_bot_enabled():
        logger.warning(f"Bot STOPPED — message to {chat_id} blocked")
        return False
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set, cannot send message")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        if not r.ok:
            logger.error(f"Telegram API error for {chat_id}: {r.text}")
            return False
        return True
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {e}")
        return False


def get_week_start(d=None):
    """Get Monday of the current week."""
    if d is None:
        d = today_moldova()
    return d - timedelta(days=d.weekday())


# ── Restaurant helpers ────────────────────────────────────────

def parse_restaurant(value, required=False):
    """Parse a restaurant string into the enum.

    Returns (restaurant | None, error_message | None).
    An empty/absent value is fine unless `required` is set.
    """
    if value is None or value == "":
        if required:
            return None, SELECTION_ERRORS["restaurant_required"]
        return None, None
    try:
        return Restaurant(value), None
    except ValueError:
        return None, SELECTION_ERRORS["restaurant_invalid"].format(value=value)


def menu_label(menu, lang):
    if menu is None:
        return "?"
    if lang == "ru" and menu.name_ru:
        return menu.name_ru
    return menu.name


def _localized(ro_value, ru_value, lang):
    if lang == "ru" and ru_value:
        return ru_value
    return ro_value or ""


# ── Auth helpers ──────────────────────────────────────────────

def create_token(username):
    payload = {
        "sub": username,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    return jwt.encode(payload, app.config["SECRET_KEY"], algorithm="HS256")


def token_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            return jsonify({"error": "Token missing"}), 401
        try:
            jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
        return f(*args, **kwargs)

    return decorated


# ── Auth endpoints ────────────────────────────────────────────

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    # str(): a JSON number would raise AttributeError on .encode() and 500.
    username = str(data.get("username", ""))
    password = str(data.get("password", ""))
    # Evaluate both halves before combining — `and` would short-circuit and make
    # a wrong username measurably faster than a wrong password.
    user_ok = hmac.compare_digest(username.encode(), ADMIN_USERNAME.encode())
    pass_ok = hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())
    if user_ok & pass_ok:
        token = create_token(username)
        return jsonify({"token": token})
    return jsonify({"error": "Invalid credentials"}), 401


# ── Menu endpoints ────────────────────────────────────────────

@app.route("/api/menus", methods=["GET"])
@token_required
def get_menus():
    day = request.args.get("day_of_week", type=int)
    week_start = request.args.get("week_start")
    restaurant, err = parse_restaurant(request.args.get("restaurant"))
    if err:
        return jsonify({"error": err}), 400

    query = Menu.query
    if day is not None:
        query = query.filter_by(day_of_week=day)
    if restaurant is not None:
        query = query.filter_by(restaurant=restaurant)
    if week_start:
        query = query.filter_by(week_start_date=date.fromisoformat(week_start))
    else:
        query = query.filter_by(week_start_date=get_week_start())

    menus = query.order_by(Menu.restaurant, Menu.sort_order).all()
    return jsonify([m.to_dict() for m in menus])


@app.route("/api/menus/today", methods=["GET"])
@token_required
def get_menus_today():
    today = today_moldova()
    dow = today.weekday()
    if dow > 4:
        return jsonify([])
    ws = get_week_start(today)
    menus = Menu.query.filter_by(day_of_week=dow, week_start_date=ws).order_by(Menu.sort_order).all()
    return jsonify([m.to_dict() for m in menus])


@app.route("/api/menus/today/approved", methods=["GET"])
def get_approved_menus_today():
    """Public endpoint for the Telegram bot / Mini App."""
    restaurant, err = parse_restaurant(request.args.get("restaurant"))
    if err:
        return jsonify({"error": err}), 400
    today = today_moldova()
    dow = today.weekday()
    if dow > 4:
        return jsonify([])
    ws = get_week_start(today)
    query = Menu.query.filter_by(day_of_week=dow, week_start_date=ws, is_approved=True)
    if restaurant is not None:
        query = query.filter_by(restaurant=restaurant)
    menus = query.order_by(Menu.restaurant, Menu.sort_order).all()
    return jsonify([m.to_dict() for m in menus])


@app.route("/api/menus", methods=["POST"])
@token_required
def create_menu():
    data = request.get_json(silent=True) or {}
    if "name" not in data or "day_of_week" not in data:
        return jsonify({"error": "name și day_of_week sunt obligatorii"}), 400

    restaurant, err = parse_restaurant(data.get("restaurant"))
    if err:
        return jsonify({"error": err}), 400
    if restaurant is None:
        restaurant = Restaurant.sezatoare

    week_start = data.get("week_start_date")
    if week_start:
        week_start = date.fromisoformat(week_start)
    else:
        week_start = get_week_start()

    menu = Menu(
        name=data["name"],
        day_of_week=data["day_of_week"],
        restaurant=restaurant,
        sort_order=data.get("sort_order", 0),
        felul_1=data.get("felul_1", ""),
        felul_2=data.get("felul_2", ""),
        garnitura=data.get("garnitura", ""),
        name_ru=data.get("name_ru", ""),
        felul_1_ru=data.get("felul_1_ru", ""),
        felul_2_ru=data.get("felul_2_ru", ""),
        garnitura_ru=data.get("garnitura_ru", ""),
        is_approved=data.get("is_approved", False),
        week_start_date=week_start,
    )
    db.session.add(menu)
    db.session.flush()

    # Andy's business lunches always ship with Felul 1 options — start with empty ones.
    if restaurant == Restaurant.andys:
        for i in range(ANDYS_DEFAULT_OPTIONS):
            db.session.add(MenuOption(menu_id=menu.id, text="", text_ru="", sort_order=i))

    db.session.commit()
    return jsonify(menu.to_dict()), 201


@app.route("/api/menus/<int:menu_id>", methods=["PUT"])
@token_required
def update_menu(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    data = request.get_json()
    if "name" in data:
        menu.name = data["name"]
    if "felul_1" in data:
        menu.felul_1 = data["felul_1"]
    if "felul_2" in data:
        menu.felul_2 = data["felul_2"]
    if "name_ru" in data:
        menu.name_ru = data["name_ru"]
    if "felul_1_ru" in data:
        menu.felul_1_ru = data["felul_1_ru"]
    if "felul_2_ru" in data:
        menu.felul_2_ru = data["felul_2_ru"]
    if "garnitura" in data:
        menu.garnitura = data["garnitura"]
    if "garnitura_ru" in data:
        menu.garnitura_ru = data["garnitura_ru"]
    if "is_approved" in data:
        menu.is_approved = data["is_approved"]
    if "day_of_week" in data:
        menu.day_of_week = data["day_of_week"]
    if "week_start_date" in data:
        menu.week_start_date = date.fromisoformat(data["week_start_date"])
    db.session.commit()
    return jsonify(menu.to_dict())


@app.route("/api/menus/<int:menu_id>", methods=["DELETE"])
@token_required
def delete_menu(menu_id):
    menu = Menu.query.get_or_404(menu_id)

    # SQLite doesn't enforce FKs: leftover selections pointing at a deleted menu
    # crash the report with a 500. Wipe every selection that references it,
    # through any of the three menu FKs (or one of its Felul 1 options).
    option_ids = [o.id for o in menu.options]
    conditions = [
        Selection.menu_id == menu_id,
        Selection.felul1_menu_id == menu_id,
        Selection.felul2_menu_id == menu_id,
    ]
    if option_ids:
        conditions.append(Selection.felul1_option_id.in_(option_ids))
    Selection.query.filter(db.or_(*conditions)).delete(synchronize_session=False)

    db.session.delete(menu)  # options go with it (cascade delete-orphan)
    db.session.commit()
    return jsonify({"ok": True})


# ── Menu options (Andy's Felul 1 choices) ────────────────────

@app.route("/api/menus/<int:menu_id>/options", methods=["POST"])
@token_required
def create_menu_option(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    data = request.get_json(silent=True) or {}
    option = MenuOption(
        menu_id=menu.id,
        text=data.get("text", ""),
        text_ru=data.get("text_ru", ""),
        sort_order=data.get("sort_order", len(menu.options)),
    )
    db.session.add(option)
    db.session.commit()
    return jsonify(option.to_dict()), 201


@app.route("/api/menu-options/<int:option_id>", methods=["PUT"])
@token_required
def update_menu_option(option_id):
    option = MenuOption.query.get_or_404(option_id)
    data = request.get_json(silent=True) or {}
    if "text" in data:
        option.text = data["text"]
    if "text_ru" in data:
        option.text_ru = data["text_ru"]
    if "sort_order" in data:
        option.sort_order = data["sort_order"]
    db.session.commit()
    return jsonify(option.to_dict())


@app.route("/api/menu-options/<int:option_id>", methods=["DELETE"])
@token_required
def delete_menu_option(option_id):
    option = MenuOption.query.get_or_404(option_id)
    # Selections pointing at this option would be orphaned → drop them.
    Selection.query.filter(
        Selection.felul1_option_id == option_id
    ).delete(synchronize_session=False)
    db.session.delete(option)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/menus/reset-content", methods=["POST"])
@token_required
def reset_menu_content():
    """Reset felul_1/felul_2 text for current week menus. Keeps menu structure."""
    today = today_moldova()
    ws = get_week_start(today)
    menus = Menu.query.filter_by(week_start_date=ws).all()
    count = 0
    for m in menus:
        m.felul_1 = ""
        m.felul_2 = ""
        m.garnitura = ""
        m.felul_1_ru = ""
        m.felul_2_ru = ""
        m.garnitura_ru = ""
        m.is_approved = False
        count += 1
    db.session.commit()
    return jsonify({"reset": count})


@app.route("/api/menus/<int:menu_id>/approve", methods=["POST"])
@token_required
def approve_menu(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    menu.is_approved = True
    db.session.commit()
    return jsonify(menu.to_dict())


def notify_menu_ready(restaurant=None):
    """Tell everyone who hasn't ordered yet that today's menu is up.

    `restaurant` is the approved restaurant (None → both were approved).
    Skips inactive users, users marked absent and users who already chose.
    Returns the number of messages actually sent.
    """
    scope = restaurant.value if restaurant is not None else "all"
    today = today_moldova()
    absent_users = {
        a.user_id for a in Attendance.query.filter_by(date=today, is_present=False).all()
    }
    users_with_selection = {
        s.user_id for s in Selection.query.filter_by(date=today).all()
    }
    sent_count = 0
    for u in User.query.filter_by(is_active=True).all():
        if u.id in absent_users or u.id in users_with_selection:
            continue
        lang = u.language or "ro"
        texts = MENU_READY_TEXTS.get(lang, MENU_READY_TEXTS["ro"])
        if send_telegram_message(u.telegram_id, texts[scope]):
            sent_count += 1
    return sent_count


@app.route("/api/menus/approve-today", methods=["POST"])
@token_required
def approve_all_today():
    data = request.get_json(silent=True) or {}
    restaurant, err = parse_restaurant(data.get("restaurant"))
    if err:
        return jsonify({"error": err}), 400

    today = today_moldova()
    dow = today.weekday()
    ws = get_week_start(today)
    query = Menu.query.filter_by(day_of_week=dow, week_start_date=ws)
    if restaurant is not None:
        query = query.filter_by(restaurant=restaurant)
    menus = query.all()
    for m in menus:
        m.is_approved = True
    ctrl = BotControl.query.get(1)
    if ctrl:
        ctrl.update_required = False
    db.session.commit()

    notified = notify_menu_ready(restaurant) if menus else 0
    return jsonify({"approved": len(menus), "notified": notified})


# ── Selection endpoints ───────────────────────────────────────

@app.route("/api/selections", methods=["GET"])
@token_required
def get_selections():
    sel_date = request.args.get("date")
    if sel_date:
        sel_date = date.fromisoformat(sel_date)
    else:
        sel_date = today_moldova()

    restaurant, err = parse_restaurant(request.args.get("restaurant"))
    if err:
        return jsonify({"error": err}), 400

    query = Selection.query.filter_by(date=sel_date)
    if restaurant is not None:
        query = query.filter_by(restaurant=restaurant)
    return jsonify([s.to_dict() for s in query.all()])


def _load_today_menu(menu_id, restaurant, today):
    """Fetch a menu and check it is today's, approved and from `restaurant`.

    Returns (menu | None, error_message | None).
    """
    menu = Menu.query.get(menu_id)
    if not menu:
        return None, SELECTION_ERRORS["menu_missing"].format(menu_id=menu_id)
    if menu.restaurant != restaurant:
        return None, SELECTION_ERRORS["menu_wrong_restaurant"].format(
            menu_id=menu_id, restaurant=restaurant.value
        )
    if not menu.is_approved:
        return None, SELECTION_ERRORS["menu_not_approved"].format(menu_id=menu_id)
    if menu.day_of_week != today.weekday() or menu.week_start_date != get_week_start(today):
        return None, SELECTION_ERRORS["menu_not_today"].format(menu_id=menu_id)
    return menu, None


def build_selection_confirmation(user, restaurant, felul1_menu, felul1_option, felul2_menu):
    """RO/RU confirmation showing the restaurant and the chosen courses."""
    lang = user.language or "ro"
    labels = FEL_LABELS.get(lang, FEL_LABELS["ro"])
    rest_label = RESTAURANT_LABELS.get(lang, RESTAURANT_LABELS["ro"])[restaurant.value]

    details = []
    if felul1_menu is not None:
        if felul1_option is not None:
            f1_text = _localized(felul1_option.text, felul1_option.text_ru, lang)
        else:
            f1_text = _localized(felul1_menu.felul_1, felul1_menu.felul_1_ru, lang)
        details.append(
            f"📋 {labels['felul1']}: {f1_text or '—'} · {menu_label(felul1_menu, lang)}"
        )
    if felul2_menu is not None:
        f2_text = _localized(felul2_menu.felul_2, felul2_menu.felul_2_ru, lang)
        details.append(
            f"📋 {labels['felul2']}: {f2_text or '—'} · {menu_label(felul2_menu, lang)}"
        )

    template = SELECTION_CONFIRM_TEXTS.get(lang, SELECTION_CONFIRM_TEXTS["ro"])
    return template.format(restaurant=rest_label, details="\n".join(details))


@app.route("/api/selections", methods=["POST"])
@require_telegram
def create_selection():
    """Create/update the caller's own selection. Identity comes from verified initData."""
    data = request.get_json(silent=True) or {}
    telegram_id = g.telegram_user["id"]
    today = today_moldova()

    # Check if ordering is still open
    settings = DailySettings.query.filter_by(date=today).first()
    if settings and not settings.ordering_open:
        return jsonify({"error": "Ordering is closed for today"}), 403

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    fara_pranz = bool(data.get("fara_pranz")) or data.get("fel_selectat") == "fara_pranz"

    felul1_menu = felul2_menu = felul1_option = None

    if fara_pranz:
        restaurant = Restaurant.sezatoare
        fel_enum = FelSelectat.fara_pranz
    else:
        restaurant, err = parse_restaurant(data.get("restaurant"), required=True)
        if err:
            return jsonify({"error": err}), 400

        felul1_menu_id = data.get("felul1_menu_id")
        felul2_menu_id = data.get("felul2_menu_id")
        felul1_option_id = data.get("felul1_option_id")

        if restaurant == Restaurant.andys:
            # Andy's: one business lunch + exactly one Felul 1 option. Felul 2 comes with it.
            if not felul1_menu_id:
                return jsonify({"error": SELECTION_ERRORS["andys_menu_required"]}), 400
            if not felul1_option_id:
                return jsonify({"error": SELECTION_ERRORS["andys_option_required"]}), 400

            felul1_menu, err = _load_today_menu(felul1_menu_id, restaurant, today)
            if err:
                return jsonify({"error": err}), 400

            felul1_option = MenuOption.query.get(felul1_option_id)
            if not felul1_option or felul1_option.menu_id != felul1_menu.id:
                return jsonify({"error": SELECTION_ERRORS["andys_option_invalid"].format(
                    option_id=felul1_option_id, menu_id=felul1_menu_id
                )}), 400

            felul2_menu = felul1_menu  # Felul 2 is fixed and included
            fel_enum = FelSelectat.ambele
        else:
            # Șezătoare: free combination, at least one course.
            if not felul1_menu_id and not felul2_menu_id:
                return jsonify({"error": SELECTION_ERRORS["sezatoare_empty"]}), 400

            if felul1_menu_id:
                felul1_menu, err = _load_today_menu(felul1_menu_id, restaurant, today)
                if err:
                    return jsonify({"error": err}), 400
            if felul2_menu_id:
                felul2_menu, err = _load_today_menu(felul2_menu_id, restaurant, today)
                if err:
                    return jsonify({"error": err}), 400

            if felul1_menu and felul2_menu:
                fel_enum = FelSelectat.ambele
            elif felul1_menu:
                fel_enum = FelSelectat.felul1
            else:
                fel_enum = FelSelectat.felul2

    felul1_menu_id = felul1_menu.id if felul1_menu else None
    felul2_menu_id = felul2_menu.id if felul2_menu else None
    felul1_option_id = felul1_option.id if felul1_option else None
    legacy_menu_id = felul1_menu_id or felul2_menu_id

    # Upsert: one order per user per day, replaced wholesale on re-submit.
    sel = Selection.query.filter_by(user_id=user.id, date=today).first()
    if not sel:
        sel = Selection(user_id=user.id, date=today)
        db.session.add(sel)
    sel.restaurant = restaurant
    sel.fel_selectat = fel_enum
    sel.menu_id = legacy_menu_id
    sel.felul1_menu_id = felul1_menu_id
    sel.felul1_option_id = felul1_option_id
    sel.felul2_menu_id = felul2_menu_id
    sel.selected_at = now_moldova()

    db.session.commit()

    # Send Telegram confirmation from Mini App
    if data.get("source", "") == "webapp":
        lang = user.language or "ro"
        if fara_pranz:
            confirm_text = SELECTION_NO_LUNCH_TEXTS.get(lang, SELECTION_NO_LUNCH_TEXTS["ro"])
        else:
            confirm_text = build_selection_confirmation(
                user, restaurant, felul1_menu, felul1_option, felul2_menu
            )
        send_telegram_message(telegram_id, confirm_text)

    return jsonify({"ok": True, "selection": sel.to_dict()})


# ── User endpoints (for bot) ─────────────────────────────────

@app.route("/api/users/register", methods=["POST"])
@require_internal
def register_user():
    data = request.get_json()
    telegram_id = data["telegram_id"]
    user = User.query.filter_by(telegram_id=telegram_id).first()
    if user:
        user.first_name = data.get("first_name", user.first_name)
        user.last_name = data.get("last_name", user.last_name)
        user.language = data.get("language", user.language)
        if "username" in data:
            user.username = data["username"]
        db.session.commit()
        return jsonify(user.to_dict()), 201

    # No such user yet. A username-only update (from the bot's update_username)
    # carries no first_name, so we cannot create a record — don't crash, just skip.
    if "first_name" not in data:
        return jsonify({"ok": True, "created": False}), 200

    user = User(
        telegram_id=telegram_id,
        first_name=data["first_name"],
        last_name=data["last_name"],
        username=data.get("username", ""),
        language=data.get("language", "ro"),
    )
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict()), 201


@app.route("/api/users/check/<int:telegram_id>", methods=["GET"])
@require_telegram_or_internal
def check_user(telegram_id):
    # An employee may only read their own record; the bot may read anyone.
    if g.telegram_user is not None and g.telegram_user["id"] != telegram_id:
        return jsonify({"error": "Forbidden"}), 403
    user = User.query.filter_by(telegram_id=telegram_id).first()
    if user:
        return jsonify({"registered": True, "user": user.to_dict()})
    return jsonify({"registered": False})


@app.route("/api/users", methods=["GET"])
@token_required
def get_users():
    users = User.query.all()
    return jsonify([u.to_dict() for u in users])


@app.route("/api/users/<int:user_id>/history", methods=["GET"])
@token_required
def get_user_history(user_id):
    """Get full selection history for a user."""
    user = User.query.get_or_404(user_id)
    selections = Selection.query.filter_by(user_id=user.id).order_by(Selection.date.desc()).all()
    return jsonify([{
        "id": s.id,
        "date": s.date.isoformat() if s.date else None,
        "fel_selectat": s.fel_selectat.value,
        "menu_name": s.menu.name if s.menu else None,
        "menu_felul_1": s.menu.felul_1 if s.menu else None,
        "menu_felul_2": s.menu.felul_2 if s.menu else None,
        "menu_garnitura": s.menu.garnitura if s.menu else None,
        "selected_at": s.selected_at.isoformat() if s.selected_at else None,
    } for s in selections])


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@token_required
def update_user(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    if "first_name" in data:
        user.first_name = data["first_name"]
    if "last_name" in data:
        user.last_name = data["last_name"]
    if "language" in data:
        user.language = data["language"]
    if "is_active" in data:
        user.is_active = data["is_active"]
    db.session.commit()
    return jsonify(user.to_dict())


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@token_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    # SQLite doesn't enforce FKs, so every child row has to go by hand. Missing
    # `attendance` here used to make deleting anyone ever marked absent fail with
    # "NOT NULL constraint failed: attendance.user_id".
    Selection.query.filter_by(user_id=user.id).delete()
    NotificationLog.query.filter_by(user_id=user.id).delete()
    Attendance.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True})


# ── Report / Export ───────────────────────────────────────────

def _person_name(selection):
    user = selection.user
    if not user:
        return "?"
    return f"{user.first_name} {user.last_name}".strip()


def _sezatoare_row(selection):
    """(row, items) for one Șezătoare selection — either course may be missing.

    A deleted menu leaves an orphan FK, so `felul1_menu` / `felul2_menu` can be
    None: skip that half instead of blowing up (old bug P2.2).
    """
    row = {}
    items = []
    sort_order = 0

    menu1 = selection.felul1_menu
    if menu1 is not None:
        row["felul1_menu"] = menu1.name
        row["felul1_menu_ru"] = menu1.name_ru or ""
        row["felul1_text"] = menu1.felul_1 or ""
        row["felul1_text_ru"] = menu1.felul_1_ru or ""
        row["sort_order_1"] = menu1.sort_order or 0
        sort_order = menu1.sort_order or 0
        items.append({
            "menu": menu1.name,
            "menu_ru": menu1.name_ru or "",
            "text": menu1.felul_1 or "",
            "text_ru": menu1.felul_1_ru or "",
        })

    menu2 = selection.felul2_menu
    if menu2 is not None:
        row["felul2_menu"] = menu2.name
        row["felul2_menu_ru"] = menu2.name_ru or ""
        row["felul2_text"] = menu2.felul_2 or ""
        row["felul2_text_ru"] = menu2.felul_2_ru or ""
        row["sort_order_2"] = menu2.sort_order or 0
        if menu1 is None:
            sort_order = menu2.sort_order or 0
        items.append({
            "menu": menu2.name,
            "menu_ru": menu2.name_ru or "",
            "text": menu2.felul_2 or "",
            "text_ru": menu2.felul_2_ru or "",
        })

    return row, items, sort_order


def _andys_row(selection):
    """(row, items) for one Andy's selection: business lunch + chosen Felul 1 option.

    The business lunch is mandatory; if the menu was deleted there is nothing to
    report, so the caller drops the selection.
    """
    menu = selection.felul1_menu
    if menu is None:
        return {}, [], 0

    option = selection.felul1_option
    opt_text = (option.text or "") if option is not None else ""
    opt_text_ru = (option.text_ru or "") if option is not None else ""

    row = {
        "menu": menu.name,
        "menu_ru": menu.name_ru or "",
        "sort_order": menu.sort_order or 0,
        "felul2_text": menu.felul_2 or "",
        "felul2_text_ru": menu.felul_2_ru or "",
        "felul1_text": opt_text,
        "felul1_text_ru": opt_text_ru,
        "felul1_option_sort": (option.sort_order or 0) if option is not None else 0,
    }

    items = []
    if option is not None:
        items.append({
            "menu": menu.name,
            "menu_ru": menu.name_ru or "",
            "text": opt_text,
            "text_ru": opt_text_ru,
        })
    items.append({
        "menu": menu.name,
        "menu_ru": menu.name_ru or "",
        "text": menu.felul_2 or "",
        "text_ru": menu.felul_2_ru or "",
    })

    return row, items, menu.sort_order or 0


@app.route("/api/report", methods=["GET"])
@token_required
def get_report():
    """Text report for ONE restaurant — the two are never combined."""
    restaurant, err = parse_restaurant(request.args.get("restaurant"), required=True)
    if err:
        return jsonify({"error": err}), 400

    sel_date = request.args.get("date")
    if sel_date:
        try:
            sel_date = date.fromisoformat(sel_date)
        except ValueError:
            return jsonify({"error": "Data invalidă (format așteptat: YYYY-MM-DD)."}), 400
    else:
        sel_date = today_moldova()

    selections = Selection.query.filter_by(date=sel_date, restaurant=restaurant).all()

    rows = []
    persons = []
    for s in selections:
        if s.fel_selectat == FelSelectat.fara_pranz:
            continue
        if restaurant == Restaurant.andys:
            row, items, sort_order = _andys_row(s)
        else:
            row, items, sort_order = _sezatoare_row(s)
        if not row:
            continue  # menus deleted — nothing left to order
        rows.append(row)
        persons.append({
            "name": _person_name(s),
            "sort_order": sort_order,
            "items": items,
        })

    if restaurant == Restaurant.andys:
        report_text = build_andys_report(rows, sel_date.isoformat(), OFFICE_ADDRESS, persons)
        total = sum(entry["orders"] for entry in count_andys(rows).values())
    else:
        report_text = build_sezatoare_report(rows, sel_date.isoformat(), OFFICE_ADDRESS, persons)
        total = sum(
            entry["felul1"]["count"] + entry["felul2"]["count"]
            for entry in count_sezatoare(rows).values()
        )

    return jsonify({
        "report_text": report_text,
        "date": sel_date.isoformat(),
        "restaurant": restaurant.value,
        "total": total,
    })


# ── Notification endpoints ────────────────────────────────────

@app.route("/api/notify/food-arrived", methods=["POST"])
@token_required
def notify_food_arrived():
    """Tell the people who ordered from a given restaurant that their food is here.

    Body: {"restaurant": "sezatoare" | "andys" | "all"} — required.
    """
    data = request.get_json(silent=True) or {}
    scope = data.get("restaurant")
    if not scope:
        return jsonify({"error": NOTIFY_ERRORS["scope_required"]}), 400
    if scope not in NOTIFY_SCOPES:
        return jsonify({"error": NOTIFY_ERRORS["scope_invalid"].format(value=scope)}), 400
    restaurants = NOTIFY_SCOPES[scope]

    today = today_moldova()
    selections = Selection.query.filter(
        Selection.date == today,
        Selection.restaurant.in_(restaurants),
    ).all()
    # Skip absent users
    absent_users = {
        a.user_id for a in Attendance.query.filter_by(date=today, is_present=False).all()
    }
    sent_count = 0
    for s in selections:
        if s.fel_selectat == FelSelectat.fara_pranz:
            continue
        if s.user_id in absent_users:
            continue
        if not s.user or not s.user.is_active:
            continue
        lang = s.user.language or "ro"
        texts = FOOD_ARRIVED_TEXTS.get(lang, FOOD_ARRIVED_TEXTS["ro"])
        if send_telegram_message(s.user.telegram_id, texts[scope]):
            sent_count += 1
        log = NotificationLog(
            user_id=s.user_id,
            type=NotificationType.food_arrived,
        )
        db.session.add(log)

    # Un-approve today's menus of the notified restaurant(s) — their cycle is done.
    dow = today.weekday()
    ws = get_week_start(today)
    today_menus = Menu.query.filter(
        Menu.day_of_week == dow,
        Menu.week_start_date == ws,
        Menu.is_approved.is_(True),
        Menu.restaurant.in_(restaurants),
    ).all()
    for m in today_menus:
        m.is_approved = False

    db.session.commit()
    return jsonify({"count": sent_count})


@app.route("/api/notify/pending-users", methods=["GET"])
@require_internal
def get_pending_users():
    """Returns users who haven't selected a menu today (for reminder bot).
    Returns empty if: bot stopped, holiday, ordering closed, no approved menus."""
    ctrl = BotControl.query.get(1)

    # Bot stopped or holiday → no reminders
    if ctrl and (not ctrl.is_enabled or ctrl.is_holiday):
        return jsonify([])

    today = today_moldova()
    dow = today.weekday()

    # Weekend → no reminders
    if dow > 4:
        return jsonify([])

    # Ordering closed → no reminders
    day_settings = DailySettings.query.filter_by(date=today).first()
    if day_settings and not day_settings.ordering_open:
        return jsonify([])

    # No approved menus → no reminders
    ws = get_week_start(today)
    approved_count = Menu.query.filter_by(
        day_of_week=dow, week_start_date=ws, is_approved=True
    ).count()
    if approved_count == 0:
        return jsonify([])

    all_users = User.query.filter_by(is_active=True).all()
    users_with_selection = {
        s.user_id for s in Selection.query.filter_by(date=today).all()
    }
    # Get users marked as absent
    absent_users = {
        a.user_id for a in Attendance.query.filter_by(date=today, is_present=False).all()
    }
    pending = [u for u in all_users if u.id not in users_with_selection and u.id not in absent_users]
    return jsonify([{"telegram_id": u.telegram_id, "language": u.language} for u in pending])


# ── Bot control (emergency stop/start) ───────────────────────

@app.route("/api/bot/status", methods=["GET"])
def bot_status():
    """Get bot status (public — used by bot process for reminder checks)."""
    ctrl = BotControl.query.get(1)
    if not ctrl:
        return jsonify({"is_enabled": True, "stopped_at": None, "started_at": None})
    return jsonify(ctrl.to_dict())


@app.route("/api/bot/stop", methods=["POST"])
@token_required
def bot_stop():
    """Emergency stop — requires admin password. Blocks ALL bot notifications."""
    data = request.get_json()
    password = data.get("password", "")
    if not hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
        return jsonify({"error": "Wrong password"}), 401

    ctrl = BotControl.query.get(1)
    if not ctrl:
        ctrl = BotControl(id=1, is_enabled=False, stopped_at=now_moldova())
        db.session.add(ctrl)
    else:
        ctrl.is_enabled = False
        ctrl.stopped_at = now_moldova()
    db.session.commit()
    logger.warning("🛑 BOT EMERGENCY STOP activated")
    return jsonify({"ok": True, "message": "Bot stopped"})


@app.route("/api/bot/start", methods=["POST"])
@token_required
def bot_start():
    """Re-enable bot — requires admin password."""
    data = request.get_json()
    password = data.get("password", "")
    if not hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode()):
        return jsonify({"error": "Wrong password"}), 401

    ctrl = BotControl.query.get(1)
    if not ctrl:
        ctrl = BotControl(id=1, is_enabled=True, started_at=now_moldova())
        db.session.add(ctrl)
    else:
        ctrl.is_enabled = True
        ctrl.started_at = now_moldova()
    db.session.commit()
    logger.info("✅ Bot re-enabled")
    return jsonify({"ok": True, "message": "Bot started"})


@app.route("/api/bot/settings", methods=["PUT"])
@token_required
def bot_update_settings():
    """Update bot settings (reminder hours, holiday)."""
    data = request.get_json()
    ctrl = BotControl.query.get(1)
    if not ctrl:
        ctrl = BotControl(id=1)
        db.session.add(ctrl)
    if "reminder_start" in data:
        ctrl.reminder_start = data["reminder_start"]
    if "reminder_end" in data:
        ctrl.reminder_end = data["reminder_end"]
    if "is_holiday" in data:
        ctrl.is_holiday = data["is_holiday"]
    if "update_required" in data:
        ctrl.update_required = data["update_required"]
    db.session.commit()
    return jsonify(ctrl.to_dict())


# ── Ordering control endpoints ────────────────────────────────

ORDERING_CLOSED_TEXTS = {
    "ro": (
        "⏰ Oops, am închis comenzile pentru azi!\n\n"
        "Observăm că nu ai apucat să-ți alegi prânzul. 😔\n\n"
        "Dacă încă vrei să comanzi, scrie rapid la @CroweTM_Office — poate mai reușim să te ajutăm! 💬\n\n"
        "Ne vedem mâine! 🌟"
    ),
    "ru": (
        "⏰ Упс, приём заказов на сегодня закрыт!\n\n"
        "Вы не успели выбрать обед. 😔\n\n"
        "Если всё ещё хотите заказать, быстро напишите в @CroweTM_Office — возможно, ещё сможем помочь! 💬\n\n"
        "Увидимся завтра! 🌟"
    ),
}


@app.route("/api/ordering/status", methods=["GET"])
def ordering_status():
    """Check if ordering is open for today (public, used by Mini App)."""
    today = today_moldova()
    settings = DailySettings.query.filter_by(date=today).first()
    if settings:
        return jsonify(settings.to_dict())
    return jsonify({"date": today.isoformat(), "ordering_open": True, "closed_at": None})


@app.route("/api/ordering/close", methods=["POST"])
@token_required
def close_ordering():
    """Close ordering for today and notify all users."""
    today = today_moldova()
    settings = DailySettings.query.filter_by(date=today).first()
    if not settings:
        settings = DailySettings(date=today, ordering_open=False, closed_at=now_moldova())
        db.session.add(settings)
    else:
        settings.ordering_open = False
        settings.closed_at = now_moldova()
    db.session.commit()

    # Notify only users who haven't selected yet (skip absent + already selected)
    all_users = User.query.filter_by(is_active=True).all()
    absent_users = {
        a.user_id for a in Attendance.query.filter_by(date=today, is_present=False).all()
    }
    users_with_selection = {
        s.user_id for s in Selection.query.filter_by(date=today).all()
    }
    sent_count = 0
    for u in all_users:
        if u.id in absent_users:
            continue
        if u.id in users_with_selection:
            continue
        lang = u.language or "ro"
        text = ORDERING_CLOSED_TEXTS.get(lang, ORDERING_CLOSED_TEXTS["ro"])
        if send_telegram_message(u.telegram_id, text):
            sent_count += 1

    return jsonify({"ok": True, "sent_count": sent_count})


@app.route("/api/ordering/open", methods=["POST"])
@token_required
def open_ordering():
    """Re-open ordering for today."""
    today = today_moldova()
    settings = DailySettings.query.filter_by(date=today).first()
    if settings:
        settings.ordering_open = True
        settings.closed_at = None
        db.session.commit()
    return jsonify({"ok": True})


# ── Attendance endpoints ─────────────────────────────────────

@app.route("/api/attendance", methods=["GET"])
@token_required
def get_attendance():
    """Get attendance for today. Returns all active users with their presence status."""
    att_date = request.args.get("date")
    if att_date:
        att_date = date.fromisoformat(att_date)
    else:
        att_date = today_moldova()

    all_users = User.query.filter_by(is_active=True).order_by(User.first_name).all()
    attendance_map = {
        a.user_id: a.is_present
        for a in Attendance.query.filter_by(date=att_date).all()
    }

    result = []
    for u in all_users:
        result.append({
            "user_id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "telegram_id": u.telegram_id,
            "is_present": attendance_map.get(u.id, True),  # default: present
        })
    return jsonify(result)


@app.route("/api/attendance", methods=["POST"])
@token_required
def set_attendance():
    """Set attendance for a user today."""
    data = request.get_json()
    user_id = data["user_id"]
    is_present = data["is_present"]
    att_date = data.get("date")
    if att_date:
        att_date = date.fromisoformat(att_date)
    else:
        att_date = today_moldova()

    existing = Attendance.query.filter_by(user_id=user_id, date=att_date).first()
    if existing:
        existing.is_present = is_present
    else:
        att = Attendance(user_id=user_id, date=att_date, is_present=is_present)
        db.session.add(att)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/attendance/bulk", methods=["POST"])
@token_required
def set_attendance_bulk():
    """Set attendance for multiple users at once."""
    data = request.get_json()
    updates = data.get("updates", [])
    att_date = data.get("date")
    if att_date:
        att_date = date.fromisoformat(att_date)
    else:
        att_date = today_moldova()

    for item in updates:
        user_id = item["user_id"]
        is_present = item["is_present"]
        existing = Attendance.query.filter_by(user_id=user_id, date=att_date).first()
        if existing:
            existing.is_present = is_present
        else:
            att = Attendance(user_id=user_id, date=att_date, is_present=is_present)
            db.session.add(att)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/attendance/stats", methods=["GET"])
@token_required
def get_attendance_stats():
    """Get attendance statistics for a date range."""
    start = request.args.get("start")
    end = request.args.get("end")

    if not start or not end:
        # Default: current week
        today = today_moldova()
        ws = get_week_start(today)
        start_date = ws
        end_date = ws + timedelta(days=4)
    else:
        start_date = date.fromisoformat(start)
        end_date = date.fromisoformat(end)

    all_users = User.query.filter_by(is_active=True).order_by(User.first_name).all()
    attendance_records = Attendance.query.filter(
        Attendance.date >= start_date,
        Attendance.date <= end_date,
    ).all()

    # Build lookup: {user_id: {date_str: is_present}}
    att_map = {}
    for a in attendance_records:
        if a.user_id not in att_map:
            att_map[a.user_id] = {}
        att_map[a.user_id][a.date.isoformat()] = a.is_present

    # Count business days in range
    business_days = 0
    d = start_date
    while d <= end_date:
        if d.weekday() < 5:
            business_days += 1
        d += timedelta(days=1)

    result = []
    for u in all_users:
        user_att = att_map.get(u.id, {})
        days_present = sum(1 for d_str, present in user_att.items() if present)
        days_absent = sum(1 for d_str, present in user_att.items() if not present)
        # Days without record count as present
        days_present += (business_days - days_present - days_absent)
        result.append({
            "user_id": u.id,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "days_present": days_present,
            "days_absent": days_absent,
            "total_days": business_days,
        })
    return jsonify(result)


# ── WebApp endpoints ──────────────────────────────────────────

@app.route("/webapp")
def serve_webapp():
    """Serve the Telegram Mini App."""
    return send_from_directory("static/webapp", "index.html")


@app.route("/api/webapp/my-selection", methods=["GET"])
@require_telegram
def webapp_my_selection():
    """Check if user already selected today (for Mini App)."""
    telegram_id = g.telegram_user["id"]

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        return jsonify({"has_selection": False})

    today = today_moldova()
    sel = Selection.query.filter_by(user_id=user.id, date=today).first()
    if not sel:
        return jsonify({"has_selection": False})

    return jsonify({
        "has_selection": True,
        "fel_selectat": sel.fel_selectat.value,
        "menu_name": sel.menu.name if sel.menu else None,
    })


@app.route("/api/webapp/ordering-status", methods=["GET"])
def webapp_ordering_status():
    """Check if ordering is open (for Mini App)."""
    today = today_moldova()
    settings = DailySettings.query.filter_by(date=today).first()
    if settings and not settings.ordering_open:
        return jsonify({"ordering_open": False})
    return jsonify({"ordering_open": True})


# ── Static uploads ───────────────────────────────────────────

@app.route("/api/static/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(os.path.join("static", "uploads"), filename)


# ── Instructions endpoints ───────────────────────────────────

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/api/instructions", methods=["GET"])
def get_instructions():
    """Public: get all active instructions (for Mini App)."""
    instructions = Instruction.query.filter_by(is_active=True).order_by(Instruction.sort_order).all()
    return jsonify([i.to_dict() for i in instructions])


@app.route("/api/instructions/all", methods=["GET"])
@token_required
def get_all_instructions():
    """Admin: get all instructions including inactive."""
    instructions = Instruction.query.order_by(Instruction.sort_order).all()
    return jsonify([i.to_dict() for i in instructions])


@app.route("/api/instructions", methods=["POST"])
@token_required
def create_instruction():
    title = request.form.get("title", "")
    title_ru = request.form.get("title_ru", "")
    content = request.form.get("content", "")
    content_ru = request.form.get("content_ru", "")
    sort_order = int(request.form.get("sort_order", 0))

    image_filename = None
    if "image" in request.files:
        file = request.files["image"]
        if file and file.filename and allowed_file(file.filename):
            import uuid
            ext = file.filename.rsplit(".", 1)[1].lower()
            image_filename = f"{uuid.uuid4().hex}.{ext}"
            file.save(os.path.join(UPLOAD_FOLDER, image_filename))

    instr = Instruction(
        title=title,
        title_ru=title_ru,
        content=content,
        content_ru=content_ru,
        image_filename=image_filename,
        sort_order=sort_order,
    )
    db.session.add(instr)
    db.session.commit()
    return jsonify(instr.to_dict()), 201


@app.route("/api/instructions/<int:instr_id>", methods=["PUT"])
@token_required
def update_instruction(instr_id):
    instr = Instruction.query.get_or_404(instr_id)

    if request.content_type and "multipart" in request.content_type:
        # Form data with possible image
        if "title" in request.form:
            instr.title = request.form["title"]
        if "title_ru" in request.form:
            instr.title_ru = request.form["title_ru"]
        if "content" in request.form:
            instr.content = request.form["content"]
        if "content_ru" in request.form:
            instr.content_ru = request.form["content_ru"]
        if "sort_order" in request.form:
            instr.sort_order = int(request.form["sort_order"])
        if "is_active" in request.form:
            instr.is_active = request.form["is_active"].lower() in ("true", "1")

        if "image" in request.files:
            file = request.files["image"]
            if file and file.filename and allowed_file(file.filename):
                # Delete old image
                if instr.image_filename:
                    old_path = os.path.join(UPLOAD_FOLDER, instr.image_filename)
                    if os.path.exists(old_path):
                        os.remove(old_path)
                import uuid
                ext = file.filename.rsplit(".", 1)[1].lower()
                instr.image_filename = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(UPLOAD_FOLDER, instr.image_filename))
    else:
        # JSON data (no image update)
        data = request.get_json()
        if "title" in data:
            instr.title = data["title"]
        if "title_ru" in data:
            instr.title_ru = data["title_ru"]
        if "content" in data:
            instr.content = data["content"]
        if "content_ru" in data:
            instr.content_ru = data["content_ru"]
        if "sort_order" in data:
            instr.sort_order = data["sort_order"]
        if "is_active" in data:
            instr.is_active = data["is_active"]

    db.session.commit()
    return jsonify(instr.to_dict())


@app.route("/api/instructions/<int:instr_id>", methods=["DELETE"])
@token_required
def delete_instruction(instr_id):
    instr = Instruction.query.get_or_404(instr_id)
    # Delete image file
    if instr.image_filename:
        img_path = os.path.join(UPLOAD_FOLDER, instr.image_filename)
        if os.path.exists(img_path):
            os.remove(img_path)
    db.session.delete(instr)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/instructions/<int:instr_id>/remove-image", methods=["POST"])
@token_required
def remove_instruction_image(instr_id):
    instr = Instruction.query.get_or_404(instr_id)
    if instr.image_filename:
        img_path = os.path.join(UPLOAD_FOLDER, instr.image_filename)
        if os.path.exists(img_path):
            os.remove(img_path)
        instr.image_filename = None
        db.session.commit()
    return jsonify(instr.to_dict())


# ── Init and seed ─────────────────────────────────────────────

def ensure_andys_menus(ws):
    """Give every weekday of week `ws` at least one Andy's business lunch.

    Runs even when the week already has menus. Without it, a database seeded
    before Andy's existed would keep an empty Andy's tab forever: seeding bails
    out early on any week that already holds Șezătoare menus.
    """
    created = 0
    for day in range(5):  # Mon–Fri
        has_andys = Menu.query.filter_by(
            week_start_date=ws, day_of_week=day, restaurant=Restaurant.andys
        ).first()
        if has_andys:
            continue
        menu = Menu(
            name="Business Lunch 1",
            name_ru="Бизнес Ланч 1",
            sort_order=0,
            day_of_week=day,
            week_start_date=ws,
            restaurant=Restaurant.andys,
        )
        for i in range(ANDYS_DEFAULT_OPTIONS):
            menu.options.append(MenuOption(text="", text_ru="", sort_order=i))
        db.session.add(menu)
        created += 1
    if created:
        db.session.commit()
        logger.info(f"Created {created} Andy's business lunch(es) for week {ws}")


def seed_default_menus():
    """Create menu templates for the current week if none exist.

    Copies content (felul_1, felul_2, translations) from the previous week
    so that menus carry over instead of starting empty each Monday.
    """
    ws = get_week_start()
    existing = Menu.query.filter_by(week_start_date=ws).first()
    if existing:
        # The week exists, but it may predate Andy's — backfill it.
        ensure_andys_menus(ws)
        return

    # Try to copy menus from the most recent previous week
    prev_ws = ws - timedelta(days=7)
    prev_menus = Menu.query.filter_by(week_start_date=prev_ws).all()

    if prev_menus:
        for pm in prev_menus:
            menu = Menu(
                name=pm.name,
                name_ru=pm.name_ru,
                sort_order=pm.sort_order,
                day_of_week=pm.day_of_week,
                week_start_date=ws,
                restaurant=pm.restaurant or Restaurant.sezatoare,
                felul_1=pm.felul_1,
                felul_2=pm.felul_2,
                garnitura=pm.garnitura,
                felul_1_ru=pm.felul_1_ru,
                felul_2_ru=pm.felul_2_ru,
                garnitura_ru=pm.garnitura_ru,
                is_approved=False,
            )
            # Andy's Felul 1 options must carry over too, otherwise the new week's
            # business lunches would have nothing to choose from.
            for po in pm.options:
                menu.options.append(MenuOption(
                    text=po.text, text_ru=po.text_ru, sort_order=po.sort_order
                ))
            db.session.add(menu)
    else:
        # No previous week data — create empty templates
        menu_templates = [
            {"name": "Lunch 1", "name_ru": "Обед 1", "sort_order": 0,
             "restaurant": Restaurant.sezatoare, "options": 0},
            {"name": "Lunch 2", "name_ru": "Обед 2", "sort_order": 1,
             "restaurant": Restaurant.sezatoare, "options": 0},
            {"name": "Business Lunch 1", "name_ru": "Бизнес Ланч 1", "sort_order": 0,
             "restaurant": Restaurant.andys, "options": ANDYS_DEFAULT_OPTIONS},
        ]
        for day in range(5):  # Mon-Fri
            for tmpl in menu_templates:
                menu = Menu(
                    name=tmpl["name"],
                    name_ru=tmpl["name_ru"],
                    sort_order=tmpl["sort_order"],
                    day_of_week=day,
                    week_start_date=ws,
                    restaurant=tmpl["restaurant"],
                )
                for i in range(tmpl["options"]):
                    menu.options.append(MenuOption(text="", text_ru="", sort_order=i))
                db.session.add(menu)
    db.session.commit()


def migrate_db():
    """Add new columns to existing tables if they don't exist."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)

    # Migrate users table
    user_columns = [col["name"] for col in inspector.get_columns("users")]
    if "username" not in user_columns:
        db.session.execute(text("ALTER TABLE users ADD COLUMN username VARCHAR(100) DEFAULT ''"))
        logger.info("Added column users.username")
        db.session.commit()

    menu_columns = [col["name"] for col in inspector.get_columns("menus")]
    new_cols = {
        "week_start_date": "DATE",
        "sort_order": "INTEGER DEFAULT 0",
        "name_ru": "VARCHAR(100) DEFAULT ''",
        "felul_1_ru": "VARCHAR(255) DEFAULT ''",
        "felul_2_ru": "VARCHAR(255) DEFAULT ''",
        "garnitura": "VARCHAR(255) DEFAULT ''",
        "garnitura_ru": "VARCHAR(255) DEFAULT ''",
        # db.Enum(Restaurant) stores the member NAME as text → default is a string.
        "restaurant": "VARCHAR(20) DEFAULT 'sezatoare'",
    }
    added_columns = []
    for col_name, col_type in new_cols.items():
        if col_name not in menu_columns:
            db.session.execute(text(f"ALTER TABLE menus ADD COLUMN {col_name} {col_type}"))
            logger.info(f"Added column menus.{col_name}")
            added_columns.append(col_name)
    # Only set defaults for newly added columns (don't overwrite existing data)
    if added_columns:
        db.session.execute(text("UPDATE menus SET sort_order = 0, name_ru = 'Обед 1' WHERE name = 'Lunch 1' AND (name_ru IS NULL OR name_ru = '')"))
        db.session.execute(text("UPDATE menus SET sort_order = 1, name_ru = 'Обед 2' WHERE name = 'Lunch 2' AND (name_ru IS NULL OR name_ru = '')"))
        db.session.execute(text("UPDATE menus SET sort_order = 2, name_ru = 'Диета' WHERE name = 'Dieta' AND (name_ru IS NULL OR name_ru = '')"))
        db.session.execute(text("UPDATE menus SET sort_order = 3, name_ru = 'Пост' WHERE name = 'Post' AND (name_ru IS NULL OR name_ru = '')"))
    if "restaurant" in added_columns:
        # Every pre-existing menu belonged to Șezătoare.
        db.session.execute(text(
            "UPDATE menus SET restaurant = 'sezatoare' WHERE restaurant IS NULL"
        ))
    # Set week_start_date for menus that don't have it
    db.session.execute(text(
        "UPDATE menus SET week_start_date = date('now', 'weekday 1', '-7 days') "
        "WHERE week_start_date IS NULL"
    ))
    db.session.commit()

    # Migrate selections table (two-restaurant model)
    selection_columns = [col["name"] for col in inspector.get_columns("selections")]
    selection_new_cols = {
        "restaurant": "VARCHAR(20) DEFAULT 'sezatoare'",
        "felul1_menu_id": "INTEGER",
        "felul1_option_id": "INTEGER",
        "felul2_menu_id": "INTEGER",
    }
    added_selection_columns = []
    for col_name, col_type in selection_new_cols.items():
        if col_name not in selection_columns:
            db.session.execute(text(f"ALTER TABLE selections ADD COLUMN {col_name} {col_type}"))
            logger.info(f"Added column selections.{col_name}")
            added_selection_columns.append(col_name)
    # Backfill ONCE, right after the columns appear — never on later boots, so we
    # can't overwrite real data. Old orders were all Șezătoare, and their courses
    # came from the single menu in the legacy `menu_id`.
    if added_selection_columns:
        db.session.execute(text(
            "UPDATE selections SET restaurant = 'sezatoare' WHERE restaurant IS NULL"
        ))
        db.session.execute(text(
            "UPDATE selections SET felul1_menu_id = menu_id "
            "WHERE fel_selectat IN ('felul1', 'ambele') AND felul1_menu_id IS NULL"
        ))
        db.session.execute(text(
            "UPDATE selections SET felul2_menu_id = menu_id "
            "WHERE fel_selectat IN ('felul2', 'ambele') AND felul2_menu_id IS NULL"
        ))
        logger.info("Backfilled selections for the two-restaurant model")
        db.session.commit()


def migrate_bot_control():
    """Add new columns to bot_control if they don't exist."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if "bot_control" not in inspector.get_table_names():
        return
    cols = [col["name"] for col in inspector.get_columns("bot_control")]
    new_cols = {
        "reminder_start": "VARCHAR(5) DEFAULT '09:00'",
        "reminder_end": "VARCHAR(5) DEFAULT '10:30'",
        "is_holiday": "BOOLEAN DEFAULT 0",
        "update_required": "BOOLEAN DEFAULT 0",
    }
    for col_name, col_type in new_cols.items():
        if col_name not in cols:
            db.session.execute(text(f"ALTER TABLE bot_control ADD COLUMN {col_name} {col_type}"))
            logger.info(f"Added column bot_control.{col_name}")
    db.session.commit()


with app.app_context():
    db.create_all()
    migrate_db()
    migrate_bot_control()
    seed_default_menus()
    # Ensure BotControl row exists
    if not BotControl.query.get(1):
        db.session.add(BotControl(id=1, is_enabled=True))
        db.session.commit()


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
