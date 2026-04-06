import os
from datetime import datetime, date, timedelta, timezone
from zoneinfo import ZoneInfo

import logging

import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import jwt

from models import db, User, Menu, Selection, NotificationLog, FelSelectat, NotificationType, Attendance, DailySettings, BotControl
from calculations import calculate_portions, generate_report_text

load_dotenv()

app = Flask(__name__, static_folder="static")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///meniubot.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
import secrets as _secrets
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", _secrets.token_hex(32))

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
FOOD_ARRIVED_TEXTS = {
    "ro": "🍽 Mâncarea a sosit! Poftă bună!",
    "ru": "🍽 Еда прибыла! Приятного аппетита!",
}

SELECTION_CONFIRM_TEXTS = {
    "ro": "✅ Mulțumim! Ați ales: {menu} — {fel}.\nVă vom anunța când mâncarea va sosi!",
    "ru": "✅ Спасибо! Вы выбрали: {menu} — {fel}.\nМы сообщим, когда еда будет готова!",
}

SELECTION_NO_LUNCH_TEXTS = {
    "ro": "✅ Ați ales: Fără prânz. Nu veți primi notificări azi.",
    "ru": "✅ Вы выбрали: Без обеда. Уведомления сегодня приходить не будут.",
}

FEL_LABELS = {
    "ro": {"felul1": "Felul 1", "felul2": "Felul 2", "ambele": "Ambele (Felul 1 + Felul 2)"},
    "ru": {"felul1": "Блюдо 1", "felul2": "Блюдо 2", "ambele": "Оба (Блюдо 1 + Блюдо 2)"},
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
    data = request.get_json()
    username = data.get("username", "")
    password = data.get("password", "")
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        token = create_token(username)
        return jsonify({"token": token})
    return jsonify({"error": "Invalid credentials"}), 401


# ── Menu endpoints ────────────────────────────────────────────

@app.route("/api/menus", methods=["GET"])
@token_required
def get_menus():
    day = request.args.get("day_of_week", type=int)
    week_start = request.args.get("week_start")

    query = Menu.query
    if day is not None:
        query = query.filter_by(day_of_week=day)
    if week_start:
        query = query.filter_by(week_start_date=date.fromisoformat(week_start))
    else:
        query = query.filter_by(week_start_date=get_week_start())

    menus = query.order_by(Menu.sort_order).all()
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
    """Public endpoint for the Telegram bot."""
    today = today_moldova()
    dow = today.weekday()
    if dow > 4:
        return jsonify([])
    ws = get_week_start(today)
    menus = Menu.query.filter_by(day_of_week=dow, week_start_date=ws, is_approved=True).order_by(Menu.sort_order).all()
    return jsonify([m.to_dict() for m in menus])


@app.route("/api/menus", methods=["POST"])
@token_required
def create_menu():
    data = request.get_json()
    week_start = data.get("week_start_date")
    if week_start:
        week_start = date.fromisoformat(week_start)
    else:
        week_start = get_week_start()

    menu = Menu(
        name=data["name"],
        day_of_week=data["day_of_week"],
        felul_1=data.get("felul_1", ""),
        felul_2=data.get("felul_2", ""),
        name_ru=data.get("name_ru", ""),
        felul_1_ru=data.get("felul_1_ru", ""),
        felul_2_ru=data.get("felul_2_ru", ""),
        is_approved=data.get("is_approved", False),
        week_start_date=week_start,
    )
    db.session.add(menu)
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
    db.session.delete(menu)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/menus/<int:menu_id>/approve", methods=["POST"])
@token_required
def approve_menu(menu_id):
    menu = Menu.query.get_or_404(menu_id)
    menu.is_approved = True
    db.session.commit()
    return jsonify(menu.to_dict())


@app.route("/api/menus/approve-today", methods=["POST"])
@token_required
def approve_all_today():
    today = today_moldova()
    dow = today.weekday()
    ws = get_week_start(today)
    menus = Menu.query.filter_by(day_of_week=dow, week_start_date=ws).all()
    for m in menus:
        m.is_approved = True
    db.session.commit()
    return jsonify({"approved": len(menus)})


# ── Selection endpoints ───────────────────────────────────────

@app.route("/api/selections", methods=["GET"])
@token_required
def get_selections():
    sel_date = request.args.get("date")
    if sel_date:
        sel_date = date.fromisoformat(sel_date)
    else:
        sel_date = today_moldova()

    selections = Selection.query.filter_by(date=sel_date).all()
    return jsonify([s.to_dict() for s in selections])


@app.route("/api/selections/alerts", methods=["GET"])
@token_required
def get_selection_alerts():
    """Get felul1-only alerts: users who need to be paired."""
    sel_date = request.args.get("date")
    if sel_date:
        sel_date = date.fromisoformat(sel_date)
    else:
        sel_date = today_moldova()

    selections = Selection.query.filter_by(date=sel_date).all()
    # Group felul1 selections by menu
    felul1_by_menu = {}
    for s in selections:
        if s.fel_selectat == FelSelectat.felul1 and s.menu:
            menu_name = s.menu.name
            if menu_name not in felul1_by_menu:
                felul1_by_menu[menu_name] = []
            felul1_by_menu[menu_name].append(
                f"{s.user.first_name} {s.user.last_name}"
            )

    alerts = []
    for menu_name, users in felul1_by_menu.items():
        count = len(users)
        if count % 2 != 0:
            alerts.append({
                "menu": menu_name,
                "count": count,
                "users": users,
                "message": f"{menu_name}: {count} x Felul 1 (nepereche!)",
            })
    return jsonify(alerts)


@app.route("/api/selections", methods=["POST"])
def create_selection():
    """Public endpoint for the Telegram bot and Mini App to create/update selections."""
    data = request.get_json()
    telegram_id = data.get("telegram_id")
    menu_id = data.get("menu_id")  # None for fara_pranz
    fel = data.get("fel_selectat")
    today = today_moldova()

    # Check if ordering is still open
    settings = DailySettings.query.filter_by(date=today).first()
    if settings and not settings.ordering_open:
        return jsonify({"error": "Ordering is closed for today"}), 403

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    try:
        fel_enum = FelSelectat(fel)
    except (ValueError, KeyError):
        return jsonify({"error": f"Invalid fel_selectat: {fel}"}), 400

    # Upsert: replace existing selection for today
    existing = Selection.query.filter_by(user_id=user.id, date=today).first()
    if existing:
        existing.menu_id = menu_id
        existing.fel_selectat = fel_enum
        existing.selected_at = now_moldova()
    else:
        sel = Selection(
            user_id=user.id,
            menu_id=menu_id,
            fel_selectat=fel_enum,
            date=today,
            selected_at=now_moldova(),
        )
        db.session.add(sel)

    db.session.commit()

    # Send Telegram confirmation from Mini App
    source = data.get("source", "")
    if source == "webapp":
        lang = user.language or "ro"
        if fel == "fara_pranz":
            confirm_text = SELECTION_NO_LUNCH_TEXTS.get(lang, SELECTION_NO_LUNCH_TEXTS["ro"])
        else:
            menu = Menu.query.get(menu_id) if menu_id else None
            mname = menu.name if menu else "?"
            if lang == "ru" and menu and menu.name_ru:
                mname = menu.name_ru
            fel_label = FEL_LABELS.get(lang, FEL_LABELS["ro"]).get(fel, fel)

            # Build detailed confirmation with menu content
            lines = [SELECTION_CONFIRM_TEXTS.get(lang, SELECTION_CONFIRM_TEXTS["ro"]).format(
                menu=mname, fel=fel_label
            )]
            if menu:
                lines.append("")
                f1_label = "Блюдо 1" if lang == "ru" else "Felul 1"
                f2_label = "Блюдо 2" if lang == "ru" else "Felul 2"
                f1 = (menu.felul_1_ru if lang == "ru" and menu.felul_1_ru else menu.felul_1) or "—"
                f2 = (menu.felul_2_ru if lang == "ru" and menu.felul_2_ru else menu.felul_2) or "—"
                if fel in ("felul1", "ambele"):
                    lines.append(f"📋 {f1_label}: {f1}")
                if fel in ("felul2", "ambele"):
                    lines.append(f"📋 {f2_label}: {f2}")
            confirm_text = "\n".join(lines)

        send_telegram_message(telegram_id, confirm_text)

    return jsonify({"ok": True})


# ── User endpoints (for bot) ─────────────────────────────────

@app.route("/api/users/register", methods=["POST"])
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
    else:
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
def check_user(telegram_id):
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
    # Delete related selections and notifications first
    Selection.query.filter_by(user_id=user.id).delete()
    NotificationLog.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    return jsonify({"ok": True})


# ── Report / Export ───────────────────────────────────────────

@app.route("/api/report", methods=["GET"])
@token_required
def get_report():
    sel_date = request.args.get("date")
    if sel_date:
        sel_date = date.fromisoformat(sel_date)
    else:
        sel_date = today_moldova()

    selections = Selection.query.filter_by(date=sel_date).all()
    sel_data = []
    for s in selections:
        if s.fel_selectat == FelSelectat.fara_pranz:
            continue
        sel_data.append({
            "menu_name": s.menu.name,
            "fel_selectat": s.fel_selectat.value,
        })

    report_text = generate_report_text(sel_data, sel_date.isoformat(), OFFICE_ADDRESS)
    portions = calculate_portions(sel_data)

    return jsonify({
        "report_text": report_text,
        "portions": portions,
        "date": sel_date.isoformat(),
    })


# ── Notification endpoints ────────────────────────────────────

@app.route("/api/notify/food-arrived", methods=["POST"])
@token_required
def notify_food_arrived():
    """Send food arrived notification to all users who ordered today."""
    today = today_moldova()
    selections = Selection.query.filter_by(date=today).all()
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
        if not s.user.is_active:
            continue
        lang = s.user.language or "ro"
        text = FOOD_ARRIVED_TEXTS.get(lang, FOOD_ARRIVED_TEXTS["ro"])
        if send_telegram_message(s.user.telegram_id, text):
            sent_count += 1
        log = NotificationLog(
            user_id=s.user_id,
            type=NotificationType.food_arrived,
        )
        db.session.add(log)

    # Un-approve today's menus (food cycle is done for the day)
    dow = today.weekday()
    ws = get_week_start(today)
    today_menus = Menu.query.filter_by(day_of_week=dow, week_start_date=ws, is_approved=True).all()
    for m in today_menus:
        m.is_approved = False

    db.session.commit()
    return jsonify({"count": sent_count})


@app.route("/api/notify/pending-users", methods=["GET"])
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
@token_required
def bot_status():
    """Get bot enabled/disabled status."""
    ctrl = BotControl.query.get(1)
    if not ctrl:
        return jsonify({"is_enabled": True, "stopped_at": None, "started_at": None})
    return jsonify(ctrl.to_dict())


@app.route("/api/bot/stop", methods=["POST"])
def bot_stop():
    """Emergency stop — requires admin password. Blocks ALL bot notifications."""
    data = request.get_json()
    password = data.get("password", "")
    if password != ADMIN_PASSWORD:
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
def bot_start():
    """Re-enable bot — requires admin password."""
    data = request.get_json()
    password = data.get("password", "")
    if password != ADMIN_PASSWORD:
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
    db.session.commit()
    return jsonify(ctrl.to_dict())


# ── Ordering control endpoints ────────────────────────────────

ORDERING_CLOSED_TEXTS = {
    "ro": "📋 Preluarea comenzilor pentru azi s-a încheiat.\nMulțumim că ați participat! Poftă bună! 🍽",
    "ru": "📋 Приём заказов на сегодня завершён.\nСпасибо за участие! Приятного аппетита! 🍽",
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

    # Send notification to all active, present users
    all_users = User.query.filter_by(is_active=True).all()
    absent_users = {
        a.user_id for a in Attendance.query.filter_by(date=today, is_present=False).all()
    }
    sent_count = 0
    for u in all_users:
        if u.id in absent_users:
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
def webapp_my_selection():
    """Check if user already selected today (for Mini App)."""
    telegram_id = request.args.get("telegram_id", type=int)
    if not telegram_id:
        return jsonify({"has_selection": False})

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


# ── Init and seed ─────────────────────────────────────────────

def seed_default_menus():
    """Create menu templates for the current week if none exist.

    Copies content (felul_1, felul_2, translations) from the previous week
    so that menus carry over instead of starting empty each Monday.
    """
    ws = get_week_start()
    existing = Menu.query.filter_by(week_start_date=ws).first()
    if existing:
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
                felul_1=pm.felul_1,
                felul_2=pm.felul_2,
                felul_1_ru=pm.felul_1_ru,
                felul_2_ru=pm.felul_2_ru,
                is_approved=False,
            )
            db.session.add(menu)
    else:
        # No previous week data — create empty templates
        menu_templates = [
            {"name": "Lunch 1", "name_ru": "Обед 1", "sort_order": 0},
            {"name": "Lunch 2", "name_ru": "Обед 2", "sort_order": 1},
            {"name": "Dieta", "name_ru": "Диета", "sort_order": 2},
            {"name": "Post", "name_ru": "Пост", "sort_order": 3},
        ]
        for day in range(5):  # Mon-Fri
            for tmpl in menu_templates:
                menu = Menu(
                    name=tmpl["name"],
                    name_ru=tmpl["name_ru"],
                    sort_order=tmpl["sort_order"],
                    day_of_week=day,
                    week_start_date=ws,
                )
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
        "sort_order": "INTEGER DEFAULT 0",
        "name_ru": "VARCHAR(100) DEFAULT ''",
        "felul_1_ru": "VARCHAR(255) DEFAULT ''",
        "felul_2_ru": "VARCHAR(255) DEFAULT ''",
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
