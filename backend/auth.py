"""Autentificare pentru clienții non-admin.

Două identități, două mecanisme:

- **Angajatul**, din Telegram Mini App. Telegram semnează `initData` cu token-ul botului.
  Serverul reverifică semnătura și extrage `user.id` din payload-ul verificat. Corpul cererii
  nu mai e crezut niciodată pe cuvânt.
- **Procesul bot**, care vorbește cu API-ul pe rețeaua internă. Se legitimează cu un secret
  partajat, `INTERNAL_API_TOKEN`.

Administratorul folosește JWT (`token_required` din app.py) — nimic din fișierul ăsta.
"""

import hashlib
import hmac
import json
import os
import time
from functools import wraps
from urllib.parse import parse_qsl

from flask import g, jsonify, request

# Vârsta maximă a unui initData acceptat. Telegram îl reemite la fiecare deschidere
# a Mini App-ului, deci o fereastră scurtă nu deranjează utilizatorul, dar limitează
# fereastra de replay dacă șirul e interceptat.
MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60

TELEGRAM_INIT_DATA_HEADER = "X-Telegram-Init-Data"
INTERNAL_TOKEN_HEADER = "X-Internal-Token"


class InitDataError(Exception):
    """initData lipsă, expirat, malformat sau cu semnătură invalidă."""


def validate_init_data(init_data, bot_token, max_age_seconds=MAX_INIT_DATA_AGE_SECONDS):
    """Verifică semnătura `initData` de la Telegram și întoarce dict-ul `user`.

    Algoritmul e cel din documentația Telegram WebApp:
      secret  = HMAC_SHA256(key="WebAppData", msg=bot_token)
      hash    = HMAC_SHA256(key=secret, msg=data_check_string)
    unde data_check_string sunt perechile `cheie=valoare`, fără `hash`, sortate
    alfabetic și unite cu `\\n`.

    Ridică InitDataError la orice eșec. Nu întoarce niciodată parțial.
    """
    if not bot_token:
        raise InitDataError("TELEGRAM_BOT_TOKEN nu e configurat pe server")
    if not init_data:
        raise InitDataError("initData lipsește")

    # strict_parsing prinde șirurile malformate în loc să le ignore tăcut
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as exc:
        raise InitDataError(f"initData malformat: {exc}") from exc

    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise InitDataError("initData nu conține hash")

    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode(), hashlib.sha256
    ).hexdigest()

    # comparație în timp constant — un `==` scurge informație prin timp
    if not hmac.compare_digest(expected_hash, received_hash):
        raise InitDataError("semnătură initData invalidă")

    auth_date = pairs.get("auth_date")
    if not auth_date or not auth_date.isdigit():
        raise InitDataError("initData nu conține auth_date valid")
    age = time.time() - int(auth_date)
    if age > max_age_seconds:
        raise InitDataError(f"initData expirat (vechime {int(age)}s)")
    if age < -300:  # toleranță pentru ceasuri ușor desincronizate
        raise InitDataError("initData are auth_date în viitor")

    raw_user = pairs.get("user")
    if not raw_user:
        raise InitDataError("initData nu conține user")
    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError as exc:
        raise InitDataError("câmpul user din initData nu e JSON") from exc

    if not isinstance(user, dict) or not isinstance(user.get("id"), int):
        raise InitDataError("user.id lipsește sau nu e întreg")

    return user


def _bot_token():
    return os.getenv("TELEGRAM_BOT_TOKEN")


def _internal_token():
    return os.getenv("INTERNAL_API_TOKEN")


def _check_internal():
    """True dacă cererea poartă un X-Internal-Token corect."""
    expected = _internal_token()
    if not expected:
        return False
    provided = request.headers.get(INTERNAL_TOKEN_HEADER, "")
    return bool(provided) and hmac.compare_digest(provided, expected)


def require_telegram(f):
    """Cere un initData valid. Pune utilizatorul verificat în `g.telegram_user`.

    Handlerul trebuie să folosească `g.telegram_user["id"]`, NU un telegram_id din corp.
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        init_data = request.headers.get(TELEGRAM_INIT_DATA_HEADER, "")
        try:
            g.telegram_user = validate_init_data(init_data, _bot_token())
        except InitDataError as exc:
            return jsonify({"error": f"Telegram auth failed: {exc}"}), 401
        return f(*args, **kwargs)

    return decorated


def require_internal(f):
    """Cere secretul partajat între backend și procesul bot."""

    @wraps(f)
    def decorated(*args, **kwargs):
        if not _check_internal():
            return jsonify({"error": "Internal token missing or invalid"}), 401
        return f(*args, **kwargs)

    return decorated


def require_telegram_or_internal(f):
    """Acceptă fie botul, fie un utilizator Telegram verificat.

    Când autentificarea e internă, `g.telegram_user` rămâne None — handlerul trebuie
    să trateze cazul (botul acționează în numele oricui).
    """

    @wraps(f)
    def decorated(*args, **kwargs):
        g.telegram_user = None
        if _check_internal():
            return f(*args, **kwargs)

        init_data = request.headers.get(TELEGRAM_INIT_DATA_HEADER, "")
        try:
            g.telegram_user = validate_init_data(init_data, _bot_token())
        except InitDataError as exc:
            return jsonify({"error": f"Auth failed: {exc}"}), 401
        return f(*args, **kwargs)

    return decorated
