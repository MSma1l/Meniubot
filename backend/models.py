import enum
from datetime import datetime, date

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
    language = db.Column(db.String(5), default="ro")
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    selections = db.relationship("Selection", backref="user", lazy="dynamic")
    notifications = db.relationship("NotificationLog", backref="user", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "telegram_id": self.telegram_id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "language": self.language,
            "registered_at": self.registered_at.isoformat() if self.registered_at else None,
            "is_active": self.is_active,
        }


class Menu(db.Model):
    __tablename__ = "menus"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Monday .. 4=Friday
    felul_1 = db.Column(db.String(255), default="")
    felul_2 = db.Column(db.String(255), default="")
    is_approved = db.Column(db.Boolean, default=False)
    week_start_date = db.Column(db.Date, nullable=False)

    selections = db.relationship("Selection", backref="menu", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "day_of_week": self.day_of_week,
            "felul_1": self.felul_1,
            "felul_2": self.felul_2,
            "is_approved": self.is_approved,
            "week_start_date": self.week_start_date.isoformat() if self.week_start_date else None,
        }


class Selection(db.Model):
    __tablename__ = "selections"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    menu_id = db.Column(db.Integer, db.ForeignKey("menus.id"), nullable=True)
    fel_selectat = db.Column(db.Enum(FelSelectat), nullable=False)
    selected_at = db.Column(db.DateTime, default=datetime.utcnow)
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
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    type = db.Column(db.Enum(NotificationType), nullable=False)
