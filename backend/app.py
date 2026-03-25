import os
from datetime import datetime, date, timedelta

import logging

import requests
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import jwt

from models import db, User, Menu, Selection, NotificationLog, FelSelectat, NotificationType
from calculations import calculate_portions, generate_report_text

load_dotenv()

app = Flask(__name__, static_folder="static")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///meniubot.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key")

CORS(app)
db.init_app(app)

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")
OFFICE_ADDRESS = os.getenv("OFFICE_ADDRESS", "str. Exemplu 123, Chișinău")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

logger = logging.getLogger(__name__)

# Localized "food arrived" messages
FOOD_ARRIVED_TEXTS = {
    "ro": "🍽 Mâncarea a sosit! Poftă bună! 📍 {address}",
    "ru": "🍽 Еда прибыла! Приятного аппетита! 📍 {address}",
}


def send_telegram_message(chat_id, text):
    """Send a message via Telegram Bot API."""
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
        d = date.today()
    return d - timedelta(days=d.weekday())


# ── Auth helpers ──────────────────────────────────────────────

def create_token(username):
    payload = {
        "sub": username,
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=24),
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

    menus = query.order_by(Menu.name).all()
    return jsonify([m.to_dict() for m in menus])


@app.route("/api/menus/today", methods=["GET"])
@token_required
def get_menus_today():
    today = date.today()
    dow = today.weekday()
    if dow > 4:
        return jsonify([])
    ws = get_week_start(today)
    menus = Menu.query.filter_by(day_of_week=dow, week_start_date=ws).order_by(Menu.name).all()
    return jsonify([m.to_dict() for m in menus])


@app.route("/api/menus/today/approved", methods=["GET"])
def get_approved_menus_today():
    """Public endpoint for the Telegram bot."""
    today = date.today()
    dow = today.weekday()
    if dow > 4:
        return jsonify([])
    ws = get_week_start(today)
    menus = Menu.query.filter_by(day_of_week=dow, week_start_date=ws, is_approved=True).order_by(Menu.name).all()
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
    today = date.today()
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
        sel_date = date.today()

    selections = Selection.query.filter_by(date=sel_date).all()
    return jsonify([s.to_dict() for s in selections])


@app.route("/api/selections", methods=["POST"])
def create_selection():
    """Public endpoint for the Telegram bot to create/update selections."""
    data = request.get_json()
    telegram_id = data.get("telegram_id")
    menu_id = data.get("menu_id")  # None for fara_pranz
    fel = data.get("fel_selectat")
    today = date.today()

    user = User.query.filter_by(telegram_id=telegram_id).first()
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Upsert: replace existing selection for today
    existing = Selection.query.filter_by(user_id=user.id, date=today).first()
    if existing:
        existing.menu_id = menu_id
        existing.fel_selectat = FelSelectat(fel)
        existing.selected_at = datetime.utcnow()
    else:
        sel = Selection(
            user_id=user.id,
            menu_id=menu_id,
            fel_selectat=FelSelectat(fel),
            date=today,
        )
        db.session.add(sel)

    db.session.commit()
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
    else:
        user = User(
            telegram_id=telegram_id,
            first_name=data["first_name"],
            last_name=data["last_name"],
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
    users = User.query.filter_by(is_active=True).all()
    return jsonify([u.to_dict() for u in users])


# ── Report / Export ───────────────────────────────────────────

@app.route("/api/report", methods=["GET"])
@token_required
def get_report():
    sel_date = request.args.get("date")
    if sel_date:
        sel_date = date.fromisoformat(sel_date)
    else:
        sel_date = date.today()

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
    today = date.today()
    selections = Selection.query.filter_by(date=today).all()
    sent_count = 0
    for s in selections:
        if s.fel_selectat == FelSelectat.fara_pranz:
            continue
        lang = s.user.language or "ro"
        text_template = FOOD_ARRIVED_TEXTS.get(lang, FOOD_ARRIVED_TEXTS["ro"])
        text = text_template.format(address=OFFICE_ADDRESS)
        if send_telegram_message(s.user.telegram_id, text):
            sent_count += 1
        log = NotificationLog(
            user_id=s.user_id,
            type=NotificationType.food_arrived,
        )
        db.session.add(log)
    db.session.commit()
    return jsonify({"count": sent_count})


@app.route("/api/notify/pending-users", methods=["GET"])
def get_pending_users():
    """Returns users who haven't selected a menu today (for reminder bot)."""
    today = date.today()
    all_users = User.query.filter_by(is_active=True).all()
    users_with_selection = {
        s.user_id for s in Selection.query.filter_by(date=today).all()
    }
    pending = [u for u in all_users if u.id not in users_with_selection]
    return jsonify([{"telegram_id": u.telegram_id, "language": u.language} for u in pending])


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

    today = date.today()
    sel = Selection.query.filter_by(user_id=user.id, date=today).first()
    if not sel:
        return jsonify({"has_selection": False})

    return jsonify({
        "has_selection": True,
        "fel_selectat": sel.fel_selectat.value,
        "menu_name": sel.menu.name if sel.menu else None,
    })


# ── Init and seed ─────────────────────────────────────────────

def seed_default_menus():
    """Create default menu templates for the current week if none exist."""
    ws = get_week_start()
    existing = Menu.query.filter_by(week_start_date=ws).first()
    if existing:
        return

    menu_names = ["Lunch 1", "Lunch 2", "Dieta", "Post"]
    for day in range(5):  # Mon-Fri
        for name in menu_names:
            menu = Menu(
                name=name,
                day_of_week=day,
                week_start_date=ws,
            )
            db.session.add(menu)
    db.session.commit()


with app.app_context():
    db.create_all()
    seed_default_menus()


if __name__ == "__main__":
    port = int(os.getenv("FLASK_PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
