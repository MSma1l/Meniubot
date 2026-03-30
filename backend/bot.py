"""Telegram bot for MeniuBot — async, python-telegram-bot v20+."""

import os
import logging
from datetime import datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo

import httpx
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, MenuButtonWebApp, MenuButtonDefault
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
WEBAPP_URL = os.getenv("WEBAPP_URL", "")  # e.g. https://yourdomain.com/webapp
OFFICE_ADDRESS = os.getenv("OFFICE_ADDRESS", "str. Exemplu 123, Chișinău")

# Moldova timezone (EET/EEST — auto-adjusts for DST)
MOLDOVA_TZ = ZoneInfo("Europe/Chisinau")

def now_md():
    return datetime.now(MOLDOVA_TZ)

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
        "food_arrived": "🍽 Mâncarea a sosit! Poftă bună!",
        "felul1": "Felul 1",
        "felul2": "Felul 2",
        "ambele": "Ambele (Felul 1 + Felul 2)",
        "fara_pranz": "🚫 Fără prânz",
        "thanks_no_lunch": "✅ Ați ales: Fără prânz. Nu veți primi notificări azi.",
        "back": "⬅️ Înapoi",
        "open_webapp": "📱 Deschide MeniuBot",
        "guide": (
            "📖 Ghid rapid MeniuBot\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🍽 Cum funcționează:\n"
            "1. Deschideți aplicația MeniuBot apăsând butonul de mai jos\n"
            "2. Alegeți meniul dorit din lista disponibilă\n"
            "3. Selectați ce doriți: Felul 1, Felul 2, sau Ambele\n"
            "4. Confirmați alegerea\n\n"
            "📋 Politica de prânz:\n"
            "• Meniurile se aprobă zilnic de către administrator\n"
            "• Puteți schimba alegerea oricând cât selectarea e deschisă\n"
            "• Veți primi notificare când mâncarea sosește\n"
            "• Dacă nu doriți prânz, selectați «Fără prânz»\n\n"
            "⏰ Program: Selectarea prânzului se face în intervalul 9:00 - 10:30\n"
            "📩 În caz de modificări, contactați @CroweTM_Office\n\n"
            "Apăsați butonul de mai jos pentru a alege meniul! 👇"
        ),
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
        "food_arrived": "🍽 Еда прибыла! Приятного аппетита!",
        "felul1": "Блюдо 1",
        "felul2": "Блюдо 2",
        "ambele": "Оба (Блюдо 1 + Блюдо 2)",
        "fara_pranz": "🚫 Без обеда",
        "thanks_no_lunch": "✅ Вы выбрали: Без обеда. Уведомления сегодня приходить не будут.",
        "back": "⬅️ Назад",
        "open_webapp": "📱 Открыть MeniuBot",
        "guide": (
            "📖 Краткое руководство MeniuBot\n"
            "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🍽 Как это работает:\n"
            "1. Откройте приложение MeniuBot, нажав кнопку ниже\n"
            "2. Выберите меню из списка\n"
            "3. Выберите: Блюдо 1, Блюдо 2 или Оба\n"
            "4. Подтвердите выбор\n\n"
            "📋 Правила обеда:\n"
            "• Меню утверждается администратором ежедневно\n"
            "• Вы можете изменить выбор, пока приём заказов открыт\n"
            "• Вы получите уведомление, когда еда прибудет\n"
            "• Если обед не нужен, выберите «Без обеда»\n\n"
            "⏰ График: Выбор обеда с 9:00 до 10:30\n"
            "📩 По вопросам изменений обращайтесь к @CroweTM_Office\n\n"
            "Нажмите кнопку ниже, чтобы выбрать меню! 👇"
        ),
    },
}


def t(lang, key):
    return TEXTS.get(lang, TEXTS["ro"]).get(key, TEXTS["ro"].get(key, key))


async def api_get(path, retries=3):
    """GET request to backend API with retry on connection errors."""
    import asyncio
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{API_BASE}{path}", timeout=10)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            if attempt < retries - 1:
                wait = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"Backend not ready, retry {attempt + 1}/{retries} in {wait}s...")
                await asyncio.sleep(wait)
            else:
                raise


async def api_post(path, data, retries=3):
    """POST request to backend API with retry on connection errors."""
    import asyncio
    for attempt in range(retries):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(f"{API_BASE}{path}", json=data, timeout=10)
                r.raise_for_status()
                return r.json()
        except httpx.ConnectError:
            if attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning(f"Backend not ready, retry {attempt + 1}/{retries} in {wait}s...")
                await asyncio.sleep(wait)
            else:
                raise


def get_webapp_button(lang):
    """Get the webapp inline keyboard button."""
    if WEBAPP_URL:
        return InlineKeyboardMarkup([[InlineKeyboardButton(
            t(lang, "open_webapp"),
            web_app=WebAppInfo(url=WEBAPP_URL),
        )]])
    return None


# ── Registration conversation ─────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🇷🇴 Română", callback_data="lang_ro"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Check if already registered
    tg_id = update.effective_user.id
    try:
        user_data = await api_get(f"/api/users/check/{tg_id}")
    except Exception as e:
        logger.error(f"Failed to check user {tg_id}: {e}")
        await update.message.reply_text(
            "⚠️ Serverul nu este disponibil momentan. Încercați din nou în câteva secunde."
        )
        return ConversationHandler.END
    if user_data.get("registered"):
        lang = user_data["user"].get("language", "ro")
        context.user_data["lang"] = lang
        context.user_data["registered"] = True

        # Show guide + webapp button
        guide_text = t(lang, "guide").format(address=OFFICE_ADDRESS)
        webapp_markup = get_webapp_button(lang)
        await update.message.reply_text(
            f"👋 {user_data['user']['first_name']}!",
        )
        await update.message.reply_text(
            guide_text,

            reply_markup=webapp_markup,
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Bine ați venit! / Добро пожаловать!\n\n"
        "Alegeți limba / Выберите язык:",
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

    # Show guide + webapp button
    context.user_data["registered"] = True
    guide_text = t(lang, "guide").format(address=OFFICE_ADDRESS)
    webapp_markup = get_webapp_button(lang)
    await update.message.reply_text(
        guide_text,
        parse_mode="MarkdownV2",
        reply_markup=webapp_markup,
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


# ── Menu command (webapp only) ───────────────────────────────

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /menu command — show webapp button."""
    tg_id = update.effective_user.id
    user_data = await api_get(f"/api/users/check/{tg_id}")
    if not user_data.get("registered"):
        await update.message.reply_text("Please /start first.")
        return
    lang = user_data["user"].get("language", "ro")
    context.user_data["lang"] = lang
    webapp_markup = get_webapp_button(lang)
    await update.message.reply_text(
        t(lang, "choose_menu"),
        reply_markup=webapp_markup,
    )


# ── Guide command ────────────────────────────────────────────

async def guide_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /guide command — show instructions."""
    tg_id = update.effective_user.id
    user_data = await api_get(f"/api/users/check/{tg_id}")
    lang = "ro"
    if user_data.get("registered"):
        lang = user_data["user"].get("language", "ro")
    context.user_data["lang"] = lang
    guide_text = t(lang, "guide").format(address=OFFICE_ADDRESS)
    webapp_markup = get_webapp_button(lang)
    await update.message.reply_text(
        guide_text,
        parse_mode="MarkdownV2",
        reply_markup=webapp_markup,
    )


# ── Reminder system ───────────────────────────────────────────

async def send_reminders(app_bot):
    """Send reminders to users who haven't selected a menu today."""
    now = now_md()
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
        # Show webapp button for reminders instead of inline menu
        keyboard = []
        if WEBAPP_URL:
            keyboard.append([InlineKeyboardButton(
                t(lang, "choose_btn"),
                web_app=WebAppInfo(url=WEBAPP_URL),
            )])
        try:
            await app_bot.send_message(
                chat_id=user["telegram_id"],
                text=t(lang, "reminder"),
                reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            )
        except Exception as e:
            logger.error(f"Failed to send reminder to {user['telegram_id']}: {e}")


# ── Food arrived notification (called from API) ──────────────

async def send_food_arrived(bot, telegram_ids_with_lang):
    """Send food arrived notification to given users."""
    for item in telegram_ids_with_lang:
        tg_id = item["telegram_id"]
        lang = item.get("language", "ro")
        text = t(lang, "food_arrived")
        try:
            await bot.send_message(chat_id=tg_id, text=text)
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
        per_message=False,
    )
    application.add_handler(conv_handler)

    # Commands
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("guide", guide_command))

    # Schedule reminders: every 5 minutes
    job_queue = application.job_queue
    job_queue.run_repeating(
        reminder_job,
        interval=300,  # 5 minutes
        first=10,  # start 10 seconds after bot starts
    )

    # Set Menu Button (the button at bottom of chat)
    async def post_init(app):
        if WEBAPP_URL:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🍽 Meniu",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            )
            logger.info(f"Menu button set to: {WEBAPP_URL}")
        else:
            await app.bot.set_chat_menu_button(
                menu_button=MenuButtonDefault()
            )
            logger.info("No WEBAPP_URL set, using default menu button")

    application.post_init = post_init

    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
