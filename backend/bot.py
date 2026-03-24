"""Telegram bot for MeniuBot — async, python-telegram-bot v20+."""

import os
import asyncio
import logging
from datetime import datetime, date, time, timedelta

import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_BASE = os.getenv("API_BASE_URL", "http://backend:5000")
OFFICE_ADDRESS = os.getenv("OFFICE_ADDRESS", "str. Exemplu 123, Chișinău")

# Conversation states
LANG, FIRST_NAME, LAST_NAME = range(3)

# Translations
TEXTS = {
    "ro": {
        "welcome": "Bine ați venit! Alegeți limba:",
        "ask_first_name": "Introduceți prenumele:",
        "ask_last_name": "Introduceți numele de familie:",
        "registered": "✅ Înregistrare completă! Bine ați venit, {name}!",
        "choose_menu": "🍽 Alegeți meniul pentru azi:",
        "no_menus": "Nu sunt meniuri disponibile pentru azi.",
        "thanks": "✅ Mulțumim! Ați ales: {menu} — {fel}.\nVă vom anunța când mâncarea va sosi!",
        "reminder": "⏰ Nu ați ales meniul de azi! Apăsați butonul de mai jos:",
        "choose_btn": "🍽 Alege meniul",
        "food_arrived": "🍽 Mâncarea a sosit! Poftă bună! 📍 {address}",
        "felul1": "Felul 1",
        "felul2": "Felul 2",
        "ambele": "Ambele (Felul 1 + Felul 2)",
        "fara_pranz": "🚫 Fără prânz",
        "thanks_no_lunch": "✅ Ați ales: Fără prânz. Nu veți primi notificări azi.",
        "back": "⬅️ Înapoi",
    },
    "ru": {
        "welcome": "Добро пожаловать! Выберите язык:",
        "ask_first_name": "Введите ваше имя:",
        "ask_last_name": "Введите вашу фамилию:",
        "registered": "✅ Регистрация завершена! Добро пожаловать, {name}!",
        "choose_menu": "🍽 Выберите меню на сегодня:",
        "no_menus": "На сегодня нет доступных меню.",
        "thanks": "✅ Спасибо! Вы выбрали: {menu} — {fel}.\nМы сообщим, когда еда будет готова!",
        "reminder": "⏰ Вы ещё не выбрали меню на сегодня! Нажмите кнопку ниже:",
        "choose_btn": "🍽 Выбрать меню",
        "food_arrived": "🍽 Еда прибыла! Приятного аппетита! 📍 {address}",
        "felul1": "Блюдо 1",
        "felul2": "Блюдо 2",
        "ambele": "Оба (Блюдо 1 + Блюдо 2)",
        "fara_pranz": "🚫 Без обеда",
        "thanks_no_lunch": "✅ Вы выбрали: Без обеда. Уведомления сегодня приходить не будут.",
        "back": "⬅️ Назад",
    },
    "en": {
        "welcome": "Welcome! Choose your language:",
        "ask_first_name": "Enter your first name:",
        "ask_last_name": "Enter your last name:",
        "registered": "✅ Registration complete! Welcome, {name}!",
        "choose_menu": "🍽 Choose today's menu:",
        "no_menus": "No menus available for today.",
        "thanks": "✅ Thank you! You chose: {menu} — {fel}.\nWe'll notify you when the food arrives!",
        "reminder": "⏰ You haven't chosen today's menu! Press the button below:",
        "choose_btn": "🍽 Choose menu",
        "food_arrived": "🍽 Food has arrived! Enjoy your meal! 📍 {address}",
        "felul1": "Course 1",
        "felul2": "Course 2",
        "ambele": "Both (Course 1 + Course 2)",
        "fara_pranz": "🚫 No lunch",
        "thanks_no_lunch": "✅ You chose: No lunch. You won't receive notifications today.",
        "back": "⬅️ Back",
    },
}


def t(lang, key):
    return TEXTS.get(lang, TEXTS["ro"]).get(key, TEXTS["ro"][key])


async def api_get(path):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{API_BASE}{path}", timeout=10)
        return r.json()


async def api_post(path, data):
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}{path}", json=data, timeout=10)
        return r.json()


# ── Registration conversation ─────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🇷🇴 Română", callback_data="lang_ro"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Check if already registered
    tg_id = update.effective_user.id
    user_data = await api_get(f"/api/users/check/{tg_id}")
    if user_data.get("registered"):
        lang = user_data["user"].get("language", "ro")
        context.user_data["lang"] = lang
        context.user_data["registered"] = True
        await update.message.reply_text(
            f"👋 {user_data['user']['first_name']}!",
        )
        await show_menu_list(update.effective_chat.id, lang, context)
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Bine ați venit! / Добро пожаловать! / Welcome!\n\n"
        "Alegeți limba / Выберите язык / Choose language:",
        reply_markup=reply_markup,
    )
    return LANG


async def lang_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data.replace("lang_", "")
    context.user_data["lang"] = lang
    await query.edit_message_text(t(lang, "ask_first_name"))
    return FIRST_NAME


async def first_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["first_name"] = update.message.text.strip()
    lang = context.user_data.get("lang", "ro")
    await update.message.reply_text(t(lang, "ask_last_name"))
    return LAST_NAME


async def last_name_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["last_name"] = update.message.text.strip()
    lang = context.user_data.get("lang", "ro")
    tg_id = update.effective_user.id

    await api_post("/api/users/register", {
        "telegram_id": tg_id,
        "first_name": context.user_data["first_name"],
        "last_name": context.user_data["last_name"],
        "language": lang,
    })

    name = f"{context.user_data['first_name']} {context.user_data['last_name']}"
    await update.message.reply_text(t(lang, "registered").format(name=name))

    context.user_data["registered"] = True
    await show_menu_list(update.effective_chat.id, lang, context)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── Menu display and selection ────────────────────────────────

async def show_menu_list(chat_id, lang, context):
    menus = await api_get("/api/menus/today/approved")
    if not menus:
        await context.bot.send_message(chat_id, t(lang, "no_menus"))
        return

    keyboard = []
    for m in menus:
        keyboard.append([InlineKeyboardButton(
            f"🍽 {m['name']}",
            callback_data=f"menu_{m['id']}",
        )])
    # "No lunch" option
    keyboard.append([InlineKeyboardButton(
        t(lang, "fara_pranz"),
        callback_data="sel_no_lunch",
    )])

    await context.bot.send_message(
        chat_id,
        t(lang, "choose_menu"),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def menu_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    menu_id = int(query.data.replace("menu_", ""))
    context.user_data["selected_menu_id"] = menu_id
    lang = context.user_data.get("lang", "ro")

    # Fetch menu details
    menus = await api_get("/api/menus/today/approved")
    menu = next((m for m in menus if m["id"] == menu_id), None)
    if not menu:
        await query.edit_message_text("Menu not found.")
        return

    text = (
        f"🍽 {menu['name']}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Felul 1: {menu['felul_1'] or '—'}\n"
        f"Felul 2: {menu['felul_2'] or '—'}\n"
        f"━━━━━━━━━━━━━━━"
    )

    keyboard = [
        [InlineKeyboardButton(f"✅ {t(lang, 'felul1')}", callback_data=f"sel_{menu_id}_felul1")],
        [InlineKeyboardButton(f"✅ {t(lang, 'felul2')}", callback_data=f"sel_{menu_id}_felul2")],
        [InlineKeyboardButton(f"✅ {t(lang, 'ambele')}", callback_data=f"sel_{menu_id}_ambele")],
        [InlineKeyboardButton(t(lang, "back"), callback_data="back_to_menus")],
    ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def no_lunch_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle 'No lunch' selection."""
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("lang", "ro")
    tg_id = update.effective_user.id

    await api_post("/api/selections", {
        "telegram_id": tg_id,
        "menu_id": None,
        "fel_selectat": "fara_pranz",
    })

    await query.edit_message_text(t(lang, "thanks_no_lunch"))


async def selection_made(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")  # sel_{menu_id}_{fel}
    menu_id = int(parts[1])
    fel = parts[2]  # felul1 / felul2 / ambele
    lang = context.user_data.get("lang", "ro")
    tg_id = update.effective_user.id

    await api_post("/api/selections", {
        "telegram_id": tg_id,
        "menu_id": menu_id,
        "fel_selectat": fel,
    })

    # Get menu name for confirmation
    menus = await api_get("/api/menus/today/approved")
    menu = next((m for m in menus if m["id"] == menu_id), None)
    menu_name = menu["name"] if menu else "?"

    fel_text = t(lang, fel)
    await query.edit_message_text(
        t(lang, "thanks").format(menu=menu_name, fel=fel_text)
    )


async def back_to_menus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = context.user_data.get("lang", "ro")

    menus = await api_get("/api/menus/today/approved")
    if not menus:
        await query.edit_message_text(t(lang, "no_menus"))
        return

    keyboard = []
    for m in menus:
        keyboard.append([InlineKeyboardButton(
            f"🍽 {m['name']}",
            callback_data=f"menu_{m['id']}",
        )])
    keyboard.append([InlineKeyboardButton(
        t(lang, "fara_pranz"),
        callback_data="sel_no_lunch",
    )])

    await query.edit_message_text(
        t(lang, "choose_menu"),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Inline command /menu ──────────────────────────────────────

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command — show available menus."""
    tg_id = update.effective_user.id
    user_data = await api_get(f"/api/users/check/{tg_id}")
    if not user_data.get("registered"):
        await update.message.reply_text("Please /start first.")
        return
    lang = user_data["user"].get("language", "ro")
    context.user_data["lang"] = lang
    await show_menu_list(update.effective_chat.id, lang, context)


# ── Reminder system ───────────────────────────────────────────

async def send_reminders(app_bot):
    """Send reminders to users who haven't selected a menu today."""
    now = datetime.now()
    # Only Mon-Fri, 09:30 - 13:00
    if now.weekday() > 4:
        return
    if now.time() < time(9, 30) or now.time() > time(13, 0):
        return

    try:
        pending = await api_get("/api/notify/pending-users")
    except Exception as e:
        logger.error(f"Failed to get pending users: {e}")
        return

    for user in pending:
        lang = user.get("language", "ro")
        keyboard = [[InlineKeyboardButton(
            t(lang, "choose_btn"),
            callback_data="show_menu_list",
        )]]
        try:
            await app_bot.send_message(
                chat_id=user["telegram_id"],
                text=t(lang, "reminder"),
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        except Exception as e:
            logger.error(f"Failed to send reminder to {user['telegram_id']}: {e}")


async def show_menu_from_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the reminder button press."""
    query = update.callback_query
    await query.answer()
    tg_id = update.effective_user.id
    user_data = await api_get(f"/api/users/check/{tg_id}")
    lang = user_data.get("user", {}).get("language", "ro") if user_data.get("registered") else "ro"
    context.user_data["lang"] = lang

    menus = await api_get("/api/menus/today/approved")
    if not menus:
        await query.edit_message_text(t(lang, "no_menus"))
        return

    keyboard = []
    for m in menus:
        keyboard.append([InlineKeyboardButton(
            f"🍽 {m['name']}",
            callback_data=f"menu_{m['id']}",
        )])
    keyboard.append([InlineKeyboardButton(
        t(lang, "fara_pranz"),
        callback_data="sel_no_lunch",
    )])

    await query.edit_message_text(
        t(lang, "choose_menu"),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Food arrived notification (called from API) ──────────────

async def send_food_arrived(bot, telegram_ids):
    """Send food arrived notification to given users."""
    for tg_id in telegram_ids:
        try:
            await bot.send_message(
                chat_id=tg_id,
                text=f"🍽 Mâncarea a sosit! Poftă bună! 📍 {OFFICE_ADDRESS}",
            )
        except Exception as e:
            logger.error(f"Failed to send food arrived to {tg_id}: {e}")


# ── Reminder job runner ───────────────────────────────────────

async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Job callback for periodic reminders."""
    await send_reminders(context.bot)


# ── Main ──────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set!")
        return

    application = Application.builder().token(BOT_TOKEN).build()

    # Registration conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG: [CallbackQueryHandler(lang_chosen, pattern=r"^lang_")],
            FIRST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, first_name_received)],
            LAST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, last_name_received)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    # Menu command
    application.add_handler(CommandHandler("menu", menu_command))

    # Callback handlers
    application.add_handler(CallbackQueryHandler(show_menu_from_reminder, pattern=r"^show_menu_list$"))
    application.add_handler(CallbackQueryHandler(back_to_menus, pattern=r"^back_to_menus$"))
    application.add_handler(CallbackQueryHandler(no_lunch_selected, pattern=r"^sel_no_lunch$"))
    application.add_handler(CallbackQueryHandler(selection_made, pattern=r"^sel_"))
    application.add_handler(CallbackQueryHandler(menu_selected, pattern=r"^menu_"))

    # Schedule reminders: every 5 minutes starting at 09:31
    job_queue = application.job_queue
    # Run every 5 minutes
    job_queue.run_repeating(
        reminder_job,
        interval=300,  # 5 minutes
        first=10,  # start 10 seconds after bot starts
    )

    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
