"""Teste pentru validarea initData de la Telegram.

Rulează: python -m unittest test_auth -v
"""

import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from auth import InitDataError, validate_init_data

BOT_TOKEN = "123456:TEST-TOKEN-ABCdef"


def make_init_data(user=None, auth_date=None, bot_token=BOT_TOKEN, extra=None, tamper=None):
    """Construiește un initData semnat corect, ca Telegram."""
    user = user if user is not None else {"id": 42, "first_name": "Ion"}
    auth_date = auth_date if auth_date is not None else int(time.time())

    pairs = {"auth_date": str(auth_date), "user": json.dumps(user)}
    if extra:
        pairs.update(extra)

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()

    if tamper:
        pairs.update(tamper)

    pairs["hash"] = digest
    return urlencode(pairs)


class TestValidateInitData(unittest.TestCase):

    def test_valid_init_data_returns_user(self):
        user = validate_init_data(make_init_data(), BOT_TOKEN)
        self.assertEqual(user["id"], 42)
        self.assertEqual(user["first_name"], "Ion")

    def test_extra_fields_are_signed_too(self):
        data = make_init_data(extra={"query_id": "AAF", "chat_type": "private"})
        user = validate_init_data(data, BOT_TOKEN)
        self.assertEqual(user["id"], 42)

    def test_wrong_bot_token_rejected(self):
        """Semnătura e legată de token. Un alt bot nu poate semna pentru noi."""
        data = make_init_data(bot_token="999:ALT-TOKEN")
        with self.assertRaises(InitDataError):
            validate_init_data(data, BOT_TOKEN)

    def test_tampered_user_id_rejected(self):
        """Cazul de atac: schimbi user.id după semnare ca să comanzi în locul altcuiva."""
        data = make_init_data(
            user={"id": 42, "first_name": "Ion"},
            tamper={"user": json.dumps({"id": 999, "first_name": "Victima"})},
        )
        with self.assertRaises(InitDataError):
            validate_init_data(data, BOT_TOKEN)

    def test_tampered_hash_rejected(self):
        data = make_init_data()
        broken = data.replace("hash=", "hash=deadbeef")
        with self.assertRaises(InitDataError):
            validate_init_data(broken, BOT_TOKEN)

    def test_missing_hash_rejected(self):
        pairs = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 1})}
        with self.assertRaises(InitDataError):
            validate_init_data(urlencode(pairs), BOT_TOKEN)

    def test_expired_init_data_rejected(self):
        old = int(time.time()) - (25 * 60 * 60)
        with self.assertRaises(InitDataError):
            validate_init_data(make_init_data(auth_date=old), BOT_TOKEN)

    def test_fresh_init_data_within_window_accepted(self):
        recent = int(time.time()) - 3600
        user = validate_init_data(make_init_data(auth_date=recent), BOT_TOKEN)
        self.assertEqual(user["id"], 42)

    def test_auth_date_in_future_rejected(self):
        future = int(time.time()) + 3600
        with self.assertRaises(InitDataError):
            validate_init_data(make_init_data(auth_date=future), BOT_TOKEN)

    def test_empty_init_data_rejected(self):
        with self.assertRaises(InitDataError):
            validate_init_data("", BOT_TOKEN)

    def test_missing_bot_token_rejected(self):
        """Fără token pe server, validarea trebuie să eșueze închis, nu deschis."""
        with self.assertRaises(InitDataError):
            validate_init_data(make_init_data(), "")

    def test_malformed_init_data_rejected(self):
        with self.assertRaises(InitDataError):
            validate_init_data("nu-e-un-query-string", BOT_TOKEN)

    def test_user_without_id_rejected(self):
        data = make_init_data(user={"first_name": "Fara ID"})
        with self.assertRaises(InitDataError):
            validate_init_data(data, BOT_TOKEN)

    def test_user_id_must_be_int(self):
        data = make_init_data(user={"id": "42", "first_name": "Ion"})
        with self.assertRaises(InitDataError):
            validate_init_data(data, BOT_TOKEN)

    def test_secret_derivation_direction(self):
        """Bug clasic: inversarea cheii cu mesajul la derivarea secretului.

        Corect: HMAC(key=b"WebAppData", msg=bot_token).
        Dacă implementarea ar fi inversată, un initData semnat cu derivarea inversă ar trece.
        """
        pairs = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 7})}
        dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        inversed_secret = hmac.new(
            BOT_TOKEN.encode(), b"WebAppData", hashlib.sha256
        ).digest()
        pairs["hash"] = hmac.new(inversed_secret, dcs.encode(), hashlib.sha256).hexdigest()

        with self.assertRaises(InitDataError):
            validate_init_data(urlencode(pairs), BOT_TOKEN)


if __name__ == "__main__":
    unittest.main()
