import enum
from datetime import datetime, date, timezone

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class FelSelectat(enum.Enum):
    felul1 = "felul1"
    felul2 = "felul2"
    ambele = "ambele"
    fara_pranz = "fara_pranz"


class NotificationType(enum.Enum):
    reminder = "reminder"
    food_arrived = "food_arrived"


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(100), nullable=True)  # @username from Telegram
    language = db.Column(db.String(5), default="ro")
    registered_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = db.Column(db.Boolean, default=True)

    selections = db.relationship("Selection", backref="user", lazy="dynamic")
    notifications = db.relationship("NotificationLog", backref="user", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "username": self.username,
            "language": self.language,
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
            "is_active": self.is_active,
        }


class Menu(db.Model):
    __tablename__ = "menus"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday .. 4=Friday
    sort_order = db.Column(db.Integer, default=0)  # 0=Lunch1, 1=Lunch2, 2=Dieta, 3=Post
    felul_1 = db.Column(db.String(255), default="")
    felul_2 = db.Column(db.String(255), default="")
    garnitura = db.Column(db.String(255), default="")  # salată, plăcintă, etc.
    # Russian translations
    name_ru = db.Column(db.String(100), default="")
    felul_1_ru = db.Column(db.String(255), default="")
    felul_2_ru = db.Column(db.String(255), default="")
    garnitura_ru = db.Column(db.String(255), default="")
    is_approved = db.Column(db.Boolean, default=False)
    week_start_date = db.Column(db.Date, nullable=False)

    selections = db.relationship("Selection", backref="menu", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "day_of_week": self.day_of_week,
            "sort_order": self.sort_order,
            "felul_1": self.felul_1,
            "felul_2": self.felul_2,
            "garnitura": self.garnitura or "",
            "name_ru": self.name_ru or "",
            "felul_1_ru": self.felul_1_ru or "",
            "felul_2_ru": self.felul_2_ru or "",
            "garnitura_ru": self.garnitura_ru or "",
            "is_approved": self.is_approved,
            "week_start_date": self.week_start_date.isoformat() if self.week_start_date else None,
        }


class Selection(db.Model):
    __tablename__ = "selections"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    menu_id = db.Column(db.Integer, db.ForeignKey("menus.id"), nullable=True)
    fel_selectat = db.Column(db.Enum(FelSelectat), nullable=False)
    selected_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    date = db.Column(db.Date, nullable=False, default=date.today)

    __table_args__ = (
        db.UniqueConstraint("user_id", "date", name="uq_user_date"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "menu_id": self.menu_id,
            "fel_selectat": self.fel_selectat.value,
            "selected_at": self.selected_at.isoformat() if self.selected_at else None,
            "date": self.date.isoformat() if self.date else None,
            "user": self.user.to_dict() if self.user else None,
            "menu": self.menu.to_dict() if self.menu else None,
        }


class NotificationLog(db.Model):
    __tablename__ = "notification_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    sent_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    type = db.Column(db.Enum(NotificationType), nullable=False)


class Attendance(db.Model):
    __tablename__ = "attendance"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False)
    is_present = db.Column(db.Boolean, default=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "date", name="uq_attendance_user_date"),
    )

    user = db.relationship("User", backref=db.backref("attendance_records", lazy="dynamic"))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "date": self.date.isoformat() if self.date else None,
            "is_present": self.is_present,
        }


class DailySettings(db.Model):
    __tablename__ = "daily_settings"

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    ordering_open = db.Column(db.Boolean, default=True)
    closed_at = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "date": self.date.isoformat() if self.date else None,
            "ordering_open": self.ordering_open,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
        }


class Instruction(db.Model):
    """Instruction/checklist items for users — managed by admin."""
    __tablename__ = "instructions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    title_ru = db.Column(db.String(200), default="")
    content = db.Column(db.Text, default="")
    content_ru = db.Column(db.Text, default="")
    image_filename = db.Column(db.String(255), nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "title_ru": self.title_ru or "",
            "content": self.content or "",
            "content_ru": self.content_ru or "",
            "image_filename": self.image_filename or "",
            "sort_order": self.sort_order,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class BotControl(db.Model):
    """Global bot settings. Only one row (id=1)."""
    __tablename__ = "bot_control"

    id = db.Column(db.Integer, primary_key=True)
    is_enabled = db.Column(db.Boolean, default=True)
    stopped_at = db.Column(db.DateTime, nullable=True)
    started_at = db.Column(db.DateTime, nullable=True)
    reminder_start = db.Column(db.String(5), default="09:00")  # HH:MM
    reminder_end = db.Column(db.String(5), default="10:30")    # HH:MM
    is_holiday = db.Column(db.Boolean, default=False)
    update_required = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            "is_enabled": self.is_enabled,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "reminder_start": self.reminder_start or "09:00",
            "reminder_end": self.reminder_end or "10:30",
            "is_holiday": self.is_holiday,
            "update_required": self.update_required,
        }
