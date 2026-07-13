"""Teste pentru procesul Telegram bot (bot.py).

Rulează: python -m unittest test_bot -v

Nimic din acest fișier nu atinge rețeaua: httpx, requests, telegram.Application
și app_bot.send_message sunt toate mock-uite. Ziua/ora sunt fixate acolo unde
contează (send_reminders), ca testele să nu depindă de momentul rulării.
"""

import asyncio  # noqa: F401
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

# Variabilele de mediu trebuie setate ÎNAINTE de import bot (le citește la import).
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-bot-token")
os.environ.setdefault("INTERNAL_API_TOKEN", "internal-test-token")
os.environ.setdefault("API_BASE_URL", "http://backend-test:5000")

import httpx  # noqa: E402

import bot  # noqa: E402


# ── Fabrici de obiecte Telegram ───────────────────────────────

def make_update(text=None, tg_id=42, username="ionel", callback_data=None):
    """Un Update fals, cu reply_text/edit_message_text ca AsyncMock."""
    update = MagicMock()
    update.effective_user.id = tg_id
    update.effective_user.username = username
    update.message.reply_text = AsyncMock()
    update.message.text = text
    if callback_data is None:
        update.callback_query = None
    else:
        update.callback_query = MagicMock()
        update.callback_query.data = callback_data
        update.callback_query.answer = AsyncMock()
        update.callback_query.edit_message_text = AsyncMock()
    return update


def make_context():
    context = MagicMock()
    context.user_data = {}
    return context


def sent_text(mock_reply, call_index=0):
    """Textul din apelul N al unui reply_text mock."""
    return mock_reply.call_args_list[call_index].args[0]


def sent_markup(mock_reply, call_index=0):
    return mock_reply.call_args_list[call_index].kwargs.get("reply_markup")


# ── t() și TEXTS ──────────────────────────────────────────────

class TestTranslations(unittest.TestCase):

    def test_t_ro(self):
        self.assertEqual(bot.t("ro", "back"), "⬅️ Înapoi")

    def test_t_ru(self):
        self.assertEqual(bot.t("ru", "back"), "⬅️ Назад")

    def test_t_unknown_language_falls_back_to_ro(self):
        self.assertEqual(bot.t("fr", "back"), bot.TEXTS["ro"]["back"])

    def test_t_unknown_key_returns_key_itself(self):
        self.assertEqual(bot.t("ro", "nu_exista"), "nu_exista")
        self.assertEqual(bot.t("ru", "nu_exista"), "nu_exista")

    def test_t_key_missing_only_in_ru_falls_back_to_ro(self):
        with patch.dict(bot.TEXTS["ru"], clear=False):
            del bot.TEXTS["ru"]["back"]
            self.assertEqual(bot.t("ru", "back"), bot.TEXTS["ro"]["back"])

    def test_texts_ro_and_ru_have_identical_keys(self):
        ro_keys = set(bot.TEXTS["ro"])
        ru_keys = set(bot.TEXTS["ru"])
        self.assertEqual(
            ro_keys, ru_keys,
            f"Chei doar în RO: {ro_keys - ru_keys}; chei doar în RU: {ru_keys - ro_keys}",
        )

    def test_texts_only_ro_and_ru(self):
        self.assertEqual(set(bot.TEXTS), {"ro", "ru"})

    def test_registered_placeholder_exists_in_both(self):
        for lang in ("ro", "ru"):
            self.assertIn("{name}", bot.TEXTS[lang]["registered"])
            self.assertIn("Ion", bot.TEXTS["ro"]["registered"].format(name="Ion"))


# ── get_webapp_button ─────────────────────────────────────────

class TestWebappButton(unittest.TestCase):

    def test_no_webapp_url_returns_none(self):
        with patch.object(bot, "WEBAPP_URL", ""):
            self.assertIsNone(bot.get_webapp_button("ro"))

    def test_with_webapp_url_returns_markup(self):
        with patch.object(bot, "WEBAPP_URL", "https://example.com/webapp"):
            markup = bot.get_webapp_button("ru")
        button = markup.inline_keyboard[0][0]
        self.assertEqual(button.text, bot.TEXTS["ru"]["open_webapp"])
        self.assertEqual(button.web_app.url, "https://example.com/webapp")


# ── now_md ────────────────────────────────────────────────────

class TestNowMd(unittest.TestCase):

    def test_now_md_is_moldova_timezone(self):
        self.assertEqual(bot.now_md().tzinfo, bot.MOLDOVA_TZ)


# ── api_get / api_post ────────────────────────────────────────

class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeAsyncClient:
    """Înlocuiește httpx.AsyncClient; nu deschide niciun socket.

    `script` e o listă de rezultate: o excepție se aruncă, orice altceva
    se întoarce ca payload JSON.
    """

    def __init__(self, script, recorder):
        self._script = script
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _next(self, method, url, headers, json_body=None):
        self._recorder.append(
            {"method": method, "url": url, "headers": headers, "json": json_body}
        )
        result = self._script.pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)

    async def get(self, url, headers=None, timeout=None):
        return self._next("GET", url, headers)

    async def post(self, url, json=None, headers=None, timeout=None):
        return self._next("POST", url, headers, json)


class TestApiHelpers(unittest.IsolatedAsyncioTestCase):

    def _patch_client(self, script):
        calls = []
        factory = MagicMock(side_effect=lambda *a, **kw: FakeAsyncClient(script, calls))
        return patch.object(bot.httpx, "AsyncClient", factory), calls

    async def test_api_get_success_and_internal_token_header(self):
        patcher, calls = self._patch_client([{"registered": True}])
        with patcher:
            result = await bot.api_get("/api/users/check/1")
        self.assertEqual(result, {"registered": True})
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], f"{bot.API_BASE}/api/users/check/1")
        self.assertEqual(calls[0]["headers"]["X-Internal-Token"], bot.INTERNAL_TOKEN)

    async def test_api_post_success_and_internal_token_header(self):
        patcher, calls = self._patch_client([{"ok": True}])
        with patcher:
            result = await bot.api_post("/api/users/register", {"telegram_id": 7})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["json"], {"telegram_id": 7})
        self.assertEqual(calls[0]["headers"]["X-Internal-Token"], bot.INTERNAL_TOKEN)

    async def test_api_get_retries_on_connect_error_then_succeeds(self):
        script = [httpx.ConnectError("backend down"), {"ok": 1}]
        patcher, calls = self._patch_client(script)
        with patcher, patch("asyncio.sleep", new=AsyncMock()) as slept:
            result = await bot.api_get("/api/bot/status")
        self.assertEqual(result, {"ok": 1})
        self.assertEqual(len(calls), 2)
        slept.assert_awaited_once_with(1)

    async def test_api_get_raises_after_all_retries(self):
        script = [httpx.ConnectError("x") for _ in range(3)]
        patcher, calls = self._patch_client(script)
        with patcher, patch("asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(httpx.ConnectError):
                await bot.api_get("/api/bot/status", retries=3)
        self.assertEqual(len(calls), 3)

    async def test_api_post_retries_on_connect_error_then_succeeds(self):
        script = [httpx.ConnectError("x"), httpx.ConnectError("x"), {"ok": True}]
        patcher, calls = self._patch_client(script)
        with patcher, patch("asyncio.sleep", new=AsyncMock()) as slept:
            result = await bot.api_post("/api/users/register", {"telegram_id": 1})
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 3)
        self.assertEqual([c.args[0] for c in slept.await_args_list], [1, 2])

    async def test_api_post_raises_after_all_retries(self):
        script = [httpx.ConnectError("x"), httpx.ConnectError("x")]
        patcher, _ = self._patch_client(script)
        with patcher, patch("asyncio.sleep", new=AsyncMock()):
            with self.assertRaises(httpx.ConnectError):
                await bot.api_post("/api/x", {}, retries=2)


# ── /start ────────────────────────────────────────────────────

class TestStart(unittest.IsolatedAsyncioTestCase):

    async def test_new_user_gets_language_question(self):
        update, context = make_update(), make_context()
        with patch.object(bot, "api_get", new=AsyncMock(return_value={"registered": False})):
            state = await bot.start(update, context)
        self.assertEqual(state, bot.LANG)
        text = sent_text(update.message.reply_text)
        self.assertIn("Bine ați venit", text)
        markup = sent_markup(update.message.reply_text)
        labels = [b.callback_data for b in markup.inline_keyboard[0]]
        self.assertEqual(labels, ["lang_ro", "lang_ru"])

    async def test_registered_user_gets_welcome_back_ro_and_conversation_ends(self):
        update, context = make_update(), make_context()
        payload = {"registered": True, "user": {"first_name": "Ion", "language": "ro"}}
        with patch.object(bot, "api_get", new=AsyncMock(return_value=payload)), \
                patch.object(bot, "WEBAPP_URL", "https://example.com/webapp"):
            state = await bot.start(update, context)
        self.assertEqual(state, bot.ConversationHandler.END)
        self.assertEqual(context.user_data["lang"], "ro")
        self.assertTrue(context.user_data["registered"])
        text = sent_text(update.message.reply_text)
        self.assertIn("Bine ai revenit, Ion", text)
        self.assertIsNotNone(sent_markup(update.message.reply_text))

    async def test_registered_user_ru_gets_russian_welcome(self):
        update, context = make_update(), make_context()
        payload = {"registered": True, "user": {"first_name": "Иван", "language": "ru"}}
        with patch.object(bot, "api_get", new=AsyncMock(return_value=payload)), \
                patch.object(bot, "WEBAPP_URL", ""):
            state = await bot.start(update, context)
        self.assertEqual(state, bot.ConversationHandler.END)
        self.assertEqual(context.user_data["lang"], "ru")
        text = sent_text(update.message.reply_text)
        self.assertIn("С возвращением, Иван", text)
        self.assertIsNone(sent_markup(update.message.reply_text))

    async def test_backend_down_shows_error_and_does_not_crash(self):
        update, context = make_update(), make_context()
        boom = AsyncMock(side_effect=httpx.ConnectError("backend down"))
        with patch.object(bot, "api_get", new=boom):
            state = await bot.start(update, context)
        self.assertEqual(state, bot.ConversationHandler.END)
        self.assertIn("Serverul nu este disponibil", sent_text(update.message.reply_text))


# ── lang_chosen ───────────────────────────────────────────────

class TestLangChosen(unittest.IsolatedAsyncioTestCase):

    async def test_ro(self):
        update, context = make_update(callback_data="lang_ro"), make_context()
        state = await bot.lang_chosen(update, context)
        self.assertEqual(state, bot.FULL_NAME)
        self.assertEqual(context.user_data["lang"], "ro")
        update.callback_query.answer.assert_awaited_once()
        update.callback_query.edit_message_text.assert_awaited_once_with(
            bot.TEXTS["ro"]["ask_full_name"]
        )

    async def test_ru(self):
        update, context = make_update(callback_data="lang_ru"), make_context()
        state = await bot.lang_chosen(update, context)
        self.assertEqual(state, bot.FULL_NAME)
        self.assertEqual(context.user_data["lang"], "ru")
        update.callback_query.edit_message_text.assert_awaited_once_with(
            bot.TEXTS["ru"]["ask_full_name"]
        )


# ── full_name_received ────────────────────────────────────────

class TestFullNameReceived(unittest.IsolatedAsyncioTestCase):

    async def _run(self, text, lang="ro", username="ionel"):
        update = make_update(text=text, tg_id=555, username=username)
        context = make_context()
        context.user_data["lang"] = lang
        post = AsyncMock(return_value={"id": 1})
        with patch.object(bot, "api_post", new=post), \
                patch.object(bot, "WEBAPP_URL", "https://example.com/webapp"):
            state = await bot.full_name_received(update, context)
        return state, update, context, post

    async def test_two_words_split_into_first_and_last(self):
        state, update, context, post = await self._run("Ion Popescu")
        self.assertEqual(state, bot.ConversationHandler.END)
        payload = post.call_args.args[1]
        self.assertEqual(payload["first_name"], "Ion")
        self.assertEqual(payload["last_name"], "Popescu")
        self.assertEqual(payload["telegram_id"], 555)
        self.assertEqual(payload["username"], "ionel")
        self.assertEqual(payload["language"], "ro")
        self.assertEqual(post.call_args.args[0], "/api/users/register")

    async def test_single_word_leaves_last_name_empty(self):
        _, update, _, post = await self._run("Ion")
        payload = post.call_args.args[1]
        self.assertEqual(payload["first_name"], "Ion")
        self.assertEqual(payload["last_name"], "")
        # numele afișat nu are spațiu în plus
        self.assertIn("Bravo, Ion!", sent_text(update.message.reply_text))

    async def test_three_words_split_on_first_space_only(self):
        _, _, _, post = await self._run("Ion Popescu Vasile")
        payload = post.call_args.args[1]
        self.assertEqual(payload["first_name"], "Ion")
        self.assertEqual(payload["last_name"], "Popescu Vasile")

    async def test_surrounding_whitespace_is_stripped(self):
        _, _, _, post = await self._run("   Ion   Popescu   ")
        payload = post.call_args.args[1]
        self.assertEqual(payload["first_name"], "Ion")
        self.assertEqual(payload["last_name"], "Popescu")

    async def test_missing_username_becomes_empty_string(self):
        _, _, _, post = await self._run("Ion Popescu", username=None)
        self.assertEqual(post.call_args.args[1]["username"], "")

    async def test_sends_confirmation_then_guide_with_button(self):
        _, update, context, _ = await self._run("Ion Popescu")
        self.assertEqual(update.message.reply_text.await_count, 2)
        self.assertIn("Ion Popescu", sent_text(update.message.reply_text, 0))
        self.assertEqual(sent_text(update.message.reply_text, 1), bot.TEXTS["ro"]["guide"])
        self.assertIsNotNone(sent_markup(update.message.reply_text, 1))
        self.assertTrue(context.user_data["registered"])

    async def test_russian_registration_uses_russian_texts(self):
        _, update, _, post = await self._run("Иван Попеску", lang="ru")
        self.assertEqual(post.call_args.args[1]["language"], "ru")
        self.assertIn("Отлично, Иван Попеску", sent_text(update.message.reply_text, 0))
        self.assertEqual(sent_text(update.message.reply_text, 1), bot.TEXTS["ru"]["guide"])

    async def test_language_defaults_to_ro_when_missing_from_context(self):
        update = make_update(text="Ion Popescu")
        context = make_context()  # fără "lang"
        with patch.object(bot, "api_post", new=AsyncMock()), \
                patch.object(bot, "WEBAPP_URL", ""):
            await bot.full_name_received(update, context)
        self.assertEqual(sent_text(update.message.reply_text, 1), bot.TEXTS["ro"]["guide"])


# ── cancel ────────────────────────────────────────────────────

class TestCancel(unittest.IsolatedAsyncioTestCase):

    async def test_cancel_ends_conversation(self):
        update, context = make_update(), make_context()
        state = await bot.cancel(update, context)
        self.assertEqual(state, bot.ConversationHandler.END)
        update.message.reply_text.assert_awaited_once_with("Cancelled.")


# ── /menu ─────────────────────────────────────────────────────

class TestMenuCommand(unittest.IsolatedAsyncioTestCase):

    async def test_registered_user_gets_webapp_button(self):
        update, context = make_update(), make_context()
        payload = {"registered": True, "user": {"first_name": "Ion", "language": "ru"}}
        with patch.object(bot, "api_get", new=AsyncMock(return_value=payload)), \
                patch.object(bot, "WEBAPP_URL", "https://example.com/webapp"):
            await bot.menu_command(update, context)
        self.assertEqual(context.user_data["lang"], "ru")
        self.assertEqual(sent_text(update.message.reply_text), bot.TEXTS["ru"]["choose_menu"])
        self.assertIsNotNone(sent_markup(update.message.reply_text))

    async def test_unregistered_user_is_told_to_start(self):
        update, context = make_update(), make_context()
        with patch.object(bot, "api_get", new=AsyncMock(return_value={"registered": False})):
            await bot.menu_command(update, context)
        update.message.reply_text.assert_awaited_once_with("Please /start first.")
        self.assertNotIn("lang", context.user_data)


# ── /guide ────────────────────────────────────────────────────

class TestGuideCommand(unittest.IsolatedAsyncioTestCase):

    async def test_registered_user_gets_guide_in_their_language(self):
        update, context = make_update(), make_context()
        payload = {"registered": True, "user": {"first_name": "Иван", "language": "ru"}}
        with patch.object(bot, "api_get", new=AsyncMock(return_value=payload)), \
                patch.object(bot, "WEBAPP_URL", "https://example.com/webapp"):
            await bot.guide_command(update, context)
        self.assertEqual(context.user_data["lang"], "ru")
        self.assertEqual(sent_text(update.message.reply_text), bot.TEXTS["ru"]["guide"])
        self.assertIsNotNone(sent_markup(update.message.reply_text))

    async def test_unregistered_user_still_gets_guide_in_ro(self):
        update, context = make_update(), make_context()
        with patch.object(bot, "api_get", new=AsyncMock(return_value={"registered": False})), \
                patch.object(bot, "WEBAPP_URL", ""):
            await bot.guide_command(update, context)
        self.assertEqual(context.user_data["lang"], "ro")
        self.assertEqual(sent_text(update.message.reply_text), bot.TEXTS["ro"]["guide"])
        self.assertIsNone(sent_markup(update.message.reply_text))


# ── update_username ───────────────────────────────────────────

class TestUpdateUsername(unittest.IsolatedAsyncioTestCase):

    async def test_updates_username_via_api(self):
        update = make_update(tg_id=99, username="noul_username")
        context = make_context()
        post = AsyncMock()
        with patch.object(bot, "api_post", new=post):
            await bot.update_username(update, context)
        post.assert_awaited_once_with(
            "/api/users/register", {"telegram_id": 99, "username": "noul_username"}
        )
        self.assertIn("_username_checked", context.user_data)

    async def test_missing_username_sent_as_empty_string(self):
        update = make_update(tg_id=99, username=None)
        context = make_context()
        post = AsyncMock()
        with patch.object(bot, "api_post", new=post):
            await bot.update_username(update, context)
        self.assertEqual(post.call_args.args[1]["username"], "")

    async def test_no_effective_user_is_a_no_op(self):
        update = make_update()
        update.effective_user = None
        context = make_context()
        post = AsyncMock()
        with patch.object(bot, "api_post", new=post):
            await bot.update_username(update, context)
        post.assert_not_awaited()

    async def test_second_call_within_the_hour_does_not_hit_the_api(self):
        update, context = make_update(), make_context()
        post = AsyncMock()
        with patch.object(bot, "api_post", new=post):
            await bot.update_username(update, context)
            await bot.update_username(update, context)
            await bot.update_username(update, context)
        self.assertEqual(post.await_count, 1)

    async def test_call_after_an_hour_hits_the_api_again(self):
        update, context = make_update(), make_context()
        post = AsyncMock()
        with patch.object(bot, "api_post", new=post):
            await bot.update_username(update, context)
            # simulăm că verificarea a fost acum 2 ore
            context.user_data["_username_checked"] -= 7200
            await bot.update_username(update, context)
        self.assertEqual(post.await_count, 2)

    async def test_api_errors_are_swallowed(self):
        update, context = make_update(), make_context()
        post = AsyncMock(side_effect=httpx.ConnectError("backend down"))
        with patch.object(bot, "api_post", new=post):
            await bot.update_username(update, context)  # nu trebuie să arunce
        post.assert_awaited_once()


# ── send_reminders / reminder_job ─────────────────────────────

WORKDAY_IN_WINDOW = datetime(2026, 3, 3, 9, 30, tzinfo=bot.MOLDOVA_TZ)   # marți 09:30
WORKDAY_BEFORE = datetime(2026, 3, 3, 8, 59, tzinfo=bot.MOLDOVA_TZ)      # marți 08:59
WORKDAY_AFTER = datetime(2026, 3, 3, 10, 31, tzinfo=bot.MOLDOVA_TZ)      # marți 10:31
SATURDAY_IN_WINDOW = datetime(2026, 3, 7, 9, 30, tzinfo=bot.MOLDOVA_TZ)  # sâmbătă 09:30

OK_STATUS = {
    "is_enabled": True,
    "is_holiday": False,
    "reminder_start": "09:00",
    "reminder_end": "10:30",
}

PENDING = [
    {"telegram_id": 111, "language": "ro"},
    {"telegram_id": 222, "language": "ru"},
]


class TestSendReminders(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.app_bot = MagicMock()
        self.app_bot.send_message = AsyncMock()

    def _api(self, status, pending=None):
        """api_get fals, rutat pe path."""
        async def fake(path, retries=3):
            if path == "/api/bot/status":
                if isinstance(status, Exception):
                    raise status
                return status
            if path == "/api/notify/pending-users":
                if isinstance(pending, Exception):
                    raise pending
                return pending or []
            raise AssertionError(f"path neașteptat: {path}")
        return AsyncMock(side_effect=fake)

    async def _run(self, status=None, pending=None, now=WORKDAY_IN_WINDOW,
                   webapp_url="https://example.com/webapp"):
        status = OK_STATUS if status is None else status
        with patch.object(bot, "api_get", new=self._api(status, pending)), \
                patch.object(bot, "now_md", return_value=now), \
                patch.object(bot, "WEBAPP_URL", webapp_url):
            await bot.send_reminders(self.app_bot)

    async def test_sends_only_to_pending_users(self):
        await self._run(pending=PENDING)
        self.assertEqual(self.app_bot.send_message.await_count, 2)
        ids = [c.kwargs["chat_id"] for c in self.app_bot.send_message.await_args_list]
        self.assertEqual(ids, [111, 222])
        first = self.app_bot.send_message.await_args_list[0].kwargs
        self.assertEqual(first["text"], bot.TEXTS["ro"]["reminder"])
        second = self.app_bot.send_message.await_args_list[1].kwargs
        self.assertEqual(second["text"], bot.TEXTS["ru"]["reminder"])
        self.assertEqual(
            second["reply_markup"].inline_keyboard[0][0].text,
            bot.TEXTS["ru"]["choose_btn"],
        )

    async def test_no_pending_users_sends_nothing(self):
        await self._run(pending=[])
        self.app_bot.send_message.assert_not_awaited()

    async def test_without_webapp_url_no_keyboard(self):
        await self._run(pending=[{"telegram_id": 111, "language": "ro"}], webapp_url="")
        self.assertIsNone(self.app_bot.send_message.await_args.kwargs["reply_markup"])

    async def test_missing_language_defaults_to_ro(self):
        await self._run(pending=[{"telegram_id": 111}])
        self.assertEqual(
            self.app_bot.send_message.await_args.kwargs["text"],
            bot.TEXTS["ro"]["reminder"],
        )

    async def test_bot_disabled_sends_nothing(self):
        await self._run(status={**OK_STATUS, "is_enabled": False}, pending=PENDING)
        self.app_bot.send_message.assert_not_awaited()

    async def test_holiday_sends_nothing(self):
        await self._run(status={**OK_STATUS, "is_holiday": True}, pending=PENDING)
        self.app_bot.send_message.assert_not_awaited()

    async def test_weekend_sends_nothing(self):
        await self._run(pending=PENDING, now=SATURDAY_IN_WINDOW)
        self.app_bot.send_message.assert_not_awaited()

    async def test_before_window_sends_nothing(self):
        await self._run(pending=PENDING, now=WORKDAY_BEFORE)
        self.app_bot.send_message.assert_not_awaited()

    async def test_after_window_sends_nothing(self):
        await self._run(pending=PENDING, now=WORKDAY_AFTER)
        self.app_bot.send_message.assert_not_awaited()

    async def test_custom_window_from_settings_is_honoured(self):
        status = {**OK_STATUS, "reminder_start": "10:00", "reminder_end": "11:00"}
        await self._run(status=status, pending=PENDING, now=WORKDAY_IN_WINDOW)  # 09:30
        self.app_bot.send_message.assert_not_awaited()

    async def test_status_endpoint_down_sends_nothing(self):
        await self._run(status=httpx.ConnectError("down"), pending=PENDING)
        self.app_bot.send_message.assert_not_awaited()

    async def test_malformed_reminder_hours_send_nothing(self):
        await self._run(status={**OK_STATUS, "reminder_start": "nope"}, pending=PENDING)
        self.app_bot.send_message.assert_not_awaited()

    async def test_pending_endpoint_down_sends_nothing(self):
        await self._run(pending=httpx.ConnectError("down"))
        self.app_bot.send_message.assert_not_awaited()

    async def test_one_failing_recipient_does_not_stop_the_rest(self):
        self.app_bot.send_message = AsyncMock(
            side_effect=[RuntimeError("blocked by user"), None]
        )
        await self._run(pending=PENDING)
        self.assertEqual(self.app_bot.send_message.await_count, 2)


class TestReminderJob(unittest.IsolatedAsyncioTestCase):

    async def test_reminder_job_delegates_to_send_reminders(self):
        context = MagicMock()
        with patch.object(bot, "send_reminders", new=AsyncMock()) as sr:
            await bot.reminder_job(context)
        sr.assert_awaited_once_with(context.bot)


# ── check_no_other_instance ───────────────────────────────────

class TestCheckNoOtherInstance(unittest.TestCase):

    def test_webhook_set_returns_false(self):
        resp = MagicMock()
        resp.json.return_value = {"ok": True, "result": {"url": "https://alt.example/hook"}}
        with patch("requests.get", return_value=resp) as get:
            self.assertFalse(bot.check_no_other_instance())
        self.assertEqual(get.call_count, 1)

    def test_no_webhook_no_pending_updates_returns_true(self):
        webhook = MagicMock()
        webhook.json.return_value = {"ok": True, "result": {"url": ""}}
        updates = MagicMock()
        updates.json.return_value = {"ok": True, "result": []}
        with patch("requests.get", side_effect=[webhook, updates]) as get:
            self.assertTrue(bot.check_no_other_instance())
        self.assertEqual(get.call_count, 2)

    def test_stale_updates_are_acknowledged(self):
        webhook = MagicMock()
        webhook.json.return_value = {"ok": True, "result": {"url": ""}}
        updates = MagicMock()
        updates.json.return_value = {"ok": True, "result": [{"update_id": 500}]}
        ack = MagicMock()
        with patch("requests.get", side_effect=[webhook, updates, ack]) as get:
            self.assertTrue(bot.check_no_other_instance())
        self.assertEqual(get.call_count, 3)
        self.assertIn("offset=501", get.call_args_list[2].args[0])

    def test_getwebhookinfo_not_ok_still_checks_updates(self):
        webhook = MagicMock()
        webhook.json.return_value = {"ok": False}
        updates = MagicMock()
        updates.json.return_value = {"ok": False}
        with patch("requests.get", side_effect=[webhook, updates]):
            self.assertTrue(bot.check_no_other_instance())

    def test_network_error_does_not_block_startup(self):
        import requests
        with patch("requests.get", side_effect=requests.RequestException("no net")):
            self.assertTrue(bot.check_no_other_instance())


# ── main() ────────────────────────────────────────────────────

class TestMain(unittest.TestCase):

    def test_no_bot_token_returns_early(self):
        with patch.object(bot, "BOT_TOKEN", ""), \
                patch.object(bot, "Application") as application:
            bot.main()
        application.builder.assert_not_called()

    def test_no_internal_token_returns_early(self):
        with patch.object(bot, "BOT_TOKEN", "tok"), \
                patch.object(bot, "INTERNAL_TOKEN", ""), \
                patch.object(bot, "Application") as application:
            bot.main()
        application.builder.assert_not_called()

    def test_other_instance_detected_stops_startup(self):
        with patch.object(bot, "BOT_TOKEN", "tok"), \
                patch.object(bot, "INTERNAL_TOKEN", "int"), \
                patch.object(bot, "check_no_other_instance", return_value=False), \
                patch.object(bot, "Application") as application:
            bot.main()
        application.builder.assert_not_called()


class TestMainWiring(unittest.IsolatedAsyncioTestCase):
    """main() construiește handlere PTB, care au nevoie de un event loop viu
    (asyncio.Lock pe Python 3.9) — de aici IsolatedAsyncioTestCase."""

    def _run_main(self, webapp_url=""):
        with patch.object(bot, "BOT_TOKEN", "tok"), \
                patch.object(bot, "INTERNAL_TOKEN", "int"), \
                patch.object(bot, "WEBAPP_URL", webapp_url), \
                patch.object(bot, "check_no_other_instance", return_value=True), \
                patch.object(bot, "Application") as application:
            bot.main()
            return application.builder.return_value.token.return_value.build.return_value

    async def test_registers_handlers_and_reminder_job_and_starts_polling(self):
        app = self._run_main()
        # conversație + 2 handlere de username + /menu + /guide
        self.assertEqual(app.add_handler.call_count, 5)
        app.job_queue.run_repeating.assert_called_once()
        kwargs = app.job_queue.run_repeating.call_args.kwargs
        self.assertEqual(kwargs["interval"], 300)
        self.assertEqual(app.job_queue.run_repeating.call_args.args[0], bot.reminder_job)
        app.run_polling.assert_called_once()
        self.assertTrue(app.run_polling.call_args.kwargs["drop_pending_updates"])

    async def _menu_button_from_post_init(self, webapp_url):
        app = self._run_main(webapp_url=webapp_url)
        fake_app = MagicMock()
        fake_app.bot.set_chat_menu_button = AsyncMock()
        # post_init citește WEBAPP_URL abia când e apelat, deci re-aplicăm patch-ul.
        with patch.object(bot, "WEBAPP_URL", webapp_url):
            await app.post_init(fake_app)
        return fake_app.bot.set_chat_menu_button.await_args.kwargs["menu_button"]

    async def test_post_init_sets_webapp_menu_button(self):
        button = await self._menu_button_from_post_init("https://example.com/webapp")
        self.assertEqual(button.web_app.url, "https://example.com/webapp")
        self.assertEqual(button.text, "🍽 Meniu")

    async def test_post_init_without_webapp_url_sets_default_button(self):
        button = await self._menu_button_from_post_init("")
        self.assertEqual(button.type, "default")


if __name__ == "__main__":
    unittest.main()
