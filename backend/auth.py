"""Autentificare pentru clienții non-admin.

Două identități, două mecanisme:

- **Angajatul**, din Telegram Mini App. Telegram semnează `initData` cu token-ul botului.
  Serverul reverifică semnătura și extrage `user.id` din payload-ul verificat. Corpul cererii
  nu mai e crezut niciodată pe cuvânt.
- **Procesul bot**, care vorbește cu API-ul pe rețeaua internă. Se legitimează cu un secret
  partajat, `INTERNAL_API_TOKEN`.

Administratorul folosește JWT (`token_required` din app.py). Pe aceeași poartă intră și
**cheile de serviciu** (`SERVICE_API_KEYS`, antetul `X-Service-Key`) — un alt server (portalul
de birou) cheamă API-ul de admin fără parola adminului, limitat la scope-urile cheii. Parsarea,
compararea și limita de rată pentru ele trăiesc mai jos; poarta propriu-zisă e în app.py.
"""

import hashlib
import hmac
import json
import logging
import math
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass
from functools import wraps
from urllib.parse import parse_qsl

from flask import g, jsonify, request

# Vârsta maximă a unui initData acceptat. Telegram îl reemite la fiecare deschidere
# a Mini App-ului, deci o fereastră scurtă nu deranjează utilizatorul, dar limitează
# fereastra de replay dacă șirul e interceptat.
MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60

TELEGRAM_INIT_DATA_HEADER = "X-Telegram-Init-Data"
INTERNAL_TOKEN_HEADER = "X-Internal-Token"
SERVICE_KEY_HEADER = "X-Service-Key"

logger = logging.getLogger(__name__)


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


# ── Chei de serviciu (server-to-server, pentru API-ul de admin) ──────────────
#
# Format `SERVICE_API_KEYS`: intrări separate prin `;`, fiecare `key_id|secret|scope,scope`.
#   SERVICE_API_KEYS=portal|<64 hex>|menus:read,orders:read
# Gol / nesetat = funcția e oprită. O intrare malformată se ignoră cu WARNING la pornire —
# mesajul numește doar poziția intrării, NICIODATĂ secretul (și nici key_id-ul, care la o
# intrare stricată poate fi chiar secretul pus pe poziția greșită).

SERVICE_SCOPES = frozenset({
    "menus:read", "menus:write",
    "orders:read",
    "users:read", "users:write",
    "budget:read", "budget:write",
    "attendance:read", "attendance:write",
    "ordering:write",
    "notify:send",
    "settings:write",
    "instructions:read", "instructions:write",
    "bot:control",
})

MIN_SERVICE_SECRET_LENGTH = 32
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


@dataclass(frozen=True)
class ServiceKey:
    key_id: str
    secret: str
    scopes: frozenset

    def __repr__(self):  # secretul nu ajunge în loguri nici printr-un repr scăpat
        return f"ServiceKey(key_id={self.key_id!r}, scopes={sorted(self.scopes)!r})"


def parse_service_keys(raw):
    """Parsează `SERVICE_API_KEYS`. Întoarce tuple de ServiceKey; intrările stricate se sar."""
    keys = []
    seen_ids, seen_secrets = set(), set()
    entries = [e.strip() for e in (raw or "").split(";")]
    for pos, entry in enumerate(entries, start=1):
        if not entry:
            continue
        parts = [p.strip() for p in entry.split("|")]
        if len(parts) != 3:
            logger.warning("SERVICE_API_KEYS: intrarea #%d ignorată — formatul cerut e "
                           "key_id|secret|scope,scope", pos)
            continue
        key_id, secret, raw_scopes = parts
        if not _KEY_ID_RE.match(key_id):
            logger.warning("SERVICE_API_KEYS: intrarea #%d ignorată — key_id invalid "
                           "(doar litere, cifre, _ . -, max 64)", pos)
            continue
        if len(secret) < MIN_SERVICE_SECRET_LENGTH:
            logger.warning("SERVICE_API_KEYS: intrarea #%d ignorată — secretul are sub %d "
                           "caractere", pos, MIN_SERVICE_SECRET_LENGTH)
            continue
        if key_id in seen_ids or secret in seen_secrets:
            logger.warning("SERVICE_API_KEYS: intrarea #%d ignorată — key_id sau secret "
                           "duplicat", pos)
            continue
        requested = {sc.strip() for sc in raw_scopes.split(",") if sc.strip()}
        unknown = requested - SERVICE_SCOPES
        if unknown:
            logger.warning("SERVICE_API_KEYS: cheia %r — scope-uri necunoscute ignorate: %s",
                           key_id, ", ".join(sorted(unknown)))
        scopes = frozenset(requested & SERVICE_SCOPES)
        if not scopes:
            logger.warning("SERVICE_API_KEYS: intrarea #%d ignorată — niciun scope valid", pos)
            continue
        seen_ids.add(key_id)
        seen_secrets.add(secret)
        keys.append(ServiceKey(key_id, secret, scopes))
    return tuple(keys)


_keys_cache = {"raw": None, "keys": ()}
_keys_lock = threading.Lock()


def service_keys():
    """Cheile configurate. Recitește mediul doar când șirul s-a schimbat."""
    raw = os.getenv("SERVICE_API_KEYS", "")
    with _keys_lock:
        if raw != _keys_cache["raw"]:
            _keys_cache["keys"] = parse_service_keys(raw)
            _keys_cache["raw"] = raw
            if _keys_cache["keys"]:
                logger.info("Chei de serviciu active: %s", ", ".join(
                    f"{k.key_id} ({','.join(sorted(k.scopes))})" for k in _keys_cache["keys"]))
        return _keys_cache["keys"]


def match_service_key(provided):
    """ServiceKey-ul al cărui secret e `provided`, sau None.

    Compară în timp constant cu FIECARE secret configurat — fără ieșire la prima potrivire,
    ca durata să nu spună nici dacă, nici cu a câta cheie s-a potrivit.
    """
    if not provided:
        return None
    provided_b = provided.encode()
    found = None
    for key in service_keys():
        if hmac.compare_digest(provided_b, key.secret.encode()):
            found = key
    return found


class SlidingWindowLimiter:
    """Fereastră glisantă în memorie, per key_id.

    Per PROCES: Meniu Bot rulează un singur proces backend (`python run.py`). Cu mai mulți
    workeri, fiecare ar avea contorul lui și limita reală s-ar înmulți cu numărul lor.
    """

    def __init__(self, limit, window_seconds=60.0, clock=time.monotonic):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._hits = {}
        self._lock = threading.Lock()

    def hit(self, key_id):
        """Înregistrează o cerere. Întoarce 0 dacă trece, altfel secundele de așteptat."""
        now = self._clock()
        with self._lock:
            q = self._hits.setdefault(key_id, deque())
            while q and q[0] <= now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                return max(1, math.ceil(q[0] + self.window - now))
            q.append(now)
            return 0

    def reset(self):
        with self._lock:
            self._hits.clear()


SERVICE_KEY_RATE_LIMIT = 120  # cereri / minut / key_id
service_key_limiter = SlidingWindowLimiter(SERVICE_KEY_RATE_LIMIT, 60.0)
