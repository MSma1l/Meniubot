#!/usr/bin/env python3
"""Smoke test end-to-end pentru fluxul zilnic MeniuBot (două restaurante).

Exercită lanțul real: login → editează meniuri și opțiuni → aprobă (pe restaurant
sau pe amândouă) → înregistrează useri → prezență → selecții la La Șezătoare și la
Andy's → securitate → cele două rapoarte → închiderea comenzilor → stopul de urgență
→ cele trei butoane „mâncarea a sosit" → curățenie.

Modelul cu două restaurante:
  • La Șezătoare — combinație liberă: Felul 1 dintr-un meniu, Felul 2 din ALT meniu,
    sau doar unul dintre ele. Fiecare fel ales = 1 porție (Maxi/Standard nu mai există).
  • Andy's — un business lunch; Felul 2 e fix și inclus, Felul 1 se alege OBLIGATORIU
    dintre opțiunile meniului (`menu_options`).
  • O singură comandă pe zi, dintr-un singur restaurant (upsert pe user+dată).

Două moduri de rulare:

  1. HTTP (implicit) — lovește un backend deja pornit.

         python smoke.py --base http://localhost:5099

     Sâmbăta și duminica rutele „today" întorc [] prin design, deci scriptul iese
     devreme cu 0 (sau, cu --force-weekday, rulează oricum și pică pe rutele „today").

  2. În proces (--in-process) — importă `backend/app.py`, îi înlocuiește
     `today_moldova()` cu o vineri fixă (2026-07-10) și `send_telegram_message()` cu
     un no-op, apoi rulează ACELEAȘI aserțiuni prin `app.test_client()`, pe o bază
     SQLite temporară. Merge oricând, inclusiv în weekend, și nu are nevoie de server.

         python smoke.py --in-process

Scrie în baza de date. În modul HTTP refuză un host non-local fără --force.
Iese cu 0 dacă toate verificările trec, 1 altfel.
"""
import argparse
import datetime
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

import requests

# Useri de test. u1/u2 → La Șezătoare, u3/u4 → Andy's, u5 → fără prânz.
TEST_TG = [999000001, 999000002, 999000003, 999000004, 999000005]
TEST_NAMES = ["SmokeUnu", "SmokeDoi", "SmokeTrei", "SmokePatru", "SmokeCinci"]

# Vinerea pe care o simulăm în modul --in-process.
FAKE_TODAY = datetime.date(2026, 7, 10)  # vineri

ok_count = 0
fail_count = 0

# True doar în modul --in-process: acolo `send_telegram_message` e înlocuit cu un
# lambda care întoarce True, deci contoarele de mesaje trimise sunt deterministe.
# Peste HTTP, serverul chiar încearcă să sune Telegram cu un token fals → 0 trimise.
strict_counts = False


def check(label, cond, detail=""):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  \033[32m✓\033[0m {label}")
    else:
        fail_count += 1
        print(f"  \033[31m✗\033[0m {label}" + (f"\n      {detail}" if detail else ""))


def check_sent(label, actual, expected):
    """Aserțiune pe numărul de mesaje Telegram trimise.

    Exactă doar în proces (unde trimiterea e simulată). Peste HTTP, tokenul de test
    nu e un token real de bot, deci serverul nu poate trimite nimic — verificăm doar
    că răspunsul e un întreg valid.
    """
    if strict_counts:
        check(f"{label} → {expected}", actual == expected, f"got {actual}")
    else:
        check(f"{label} (întreg; exact doar --in-process)", isinstance(actual, int),
              f"got {actual!r}")


def d(status, data):
    return f"got {status}: {str(data)[:140]}"


def make_init_data(telegram_id, first_name, bot_token):
    """Construiește un initData VALID, semnat exact ca Telegram WebApp.

    secret = HMAC_SHA256(key="WebAppData", msg=bot_token)
    hash   = HMAC_SHA256(key=secret, msg=data_check_string)
    unde data_check_string sunt perechile cheie=valoare (fără hash), sortate
    alfabetic și unite cu '\\n'.
    """
    pairs = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": first_name}),
    }
    data_check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(
        secret, data_check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(pairs)


# ── Client uniform ────────────────────────────────────────────
# Aserțiunile nu trebuie să știe dacă vorbesc prin rețea sau prin test_client.
# Ambele implementări întorc (status_code, json | None).

class Client:
    def __init__(self):
        self.auth_headers = {}

    def _send(self, method, path, headers, body):  # pragma: no cover - abstract
        raise NotImplementedError

    def request(self, method, path, headers=None, json=None, auth=True):
        """auth=False → cerere anonimă (fără Authorization) pentru testele de securitate."""
        h = dict(self.auth_headers) if auth else {}
        if headers:
            h.update(headers)
        return self._send(method, path, h, json)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


class HttpClient(Client):
    def __init__(self, base):
        super().__init__()
        self.base = base.rstrip("/")

    def _send(self, method, path, headers, body):
        kw = {"headers": headers, "timeout": 20}
        if body is not None:
            kw["json"] = body
        r = requests.request(method, self.base + path, **kw)
        try:
            data = r.json()
        except ValueError:
            data = None
        return r.status_code, data


class InProcessClient(Client):
    def __init__(self, flask_app):
        super().__init__()
        self.client = flask_app.test_client()

    def _send(self, method, path, headers, body):
        kw = {"headers": headers}
        if body is not None:
            kw["json"] = body
        r = self.client.open(path, method=method, **kw)
        return r.status_code, r.get_json(silent=True)


def load_app_in_process(args, db_path):
    """Importă backend/app.py cu un mediu de test și îi falsifică ziua.

    Variabilele de mediu TREBUIE setate înainte de import: app.py ridică RuntimeError
    la import dacă SECRET_KEY sau INTERNAL_API_TOKEN lipsesc, și tot la import rulează
    db.create_all(), migrațiile și seed-ul.
    """
    backend = Path(args.backend).resolve()
    if not (backend / "app.py").exists():
        sys.exit(f"REFUZ: nu găsesc app.py în {backend}. Folosește --backend.")

    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SECRET_KEY"] = "0123456789abcdef0123456789abcdef"  # 32 caractere
    os.environ["INTERNAL_API_TOKEN"] = args.internal_token
    os.environ["TELEGRAM_BOT_TOKEN"] = args.bot_token
    os.environ["ADMIN_USERNAME"] = args.user
    os.environ["ADMIN_PASSWORD"] = args.password

    sys.path.insert(0, str(backend))
    import app as app_module  # noqa: E402  (import târziu, după setarea mediului)

    # Ziua fixă: o vineri. Tot business logic-ul trece prin today_moldova(),
    # deci e de ajuns să înlocuim funcția din modul.
    app_module.today_moldova = lambda: FAKE_TODAY
    app_module.now_moldova = lambda: datetime.datetime(
        2026, 7, 10, 12, 0, tzinfo=app_module.MOLDOVA_TZ
    )
    # Nimic nu pleacă spre Telegram; contoarele devin deterministe.
    app_module.send_telegram_message = lambda chat_id, text: True

    # Seed-ul de la import a folosit ziua reală. Dacă săptămâna simulată e alta,
    # semănăm și meniurile ei.
    with app_module.app.app_context():
        app_module.seed_default_menus()

    return app_module


def main():
    global strict_counts

    here = Path(__file__).resolve()
    default_backend = here.parents[4] / "backend"

    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--bot-token", default="test-bot-token",
                    help="tokenul botului cu care se semnează initData (trebuie egal cu TELEGRAM_BOT_TOKEN al serverului)")
    ap.add_argument("--internal-token", default="test-internal-token",
                    help="secretul intern bot↔API (trebuie egal cu INTERNAL_API_TOKEN al serverului)")
    ap.add_argument("--force", action="store_true", help="permite rularea pe host non-local")
    ap.add_argument("--in-process", action="store_true",
                    help="importă backend/app.py, falsifică ziua (vineri 2026-07-10) și rulează prin test_client — merge și în weekend")
    ap.add_argument("--force-weekday", action="store_true",
                    help="[doar HTTP] nu sări peste teste în weekend; rutele „today\" vor întoarce [] și aserțiunile lor vor pica. Folosește mai bine --in-process")
    ap.add_argument("--backend", default=str(default_backend),
                    help="[doar --in-process] directorul backend (implicit: cel din repo)")
    args = ap.parse_args()

    tmp_db = None
    if args.in_process:
        fd, tmp_db = tempfile.mkstemp(prefix="meniubot-smoke-", suffix=".db")
        os.close(fd)
        os.unlink(tmp_db)  # SQLAlchemy îl creează singur; vrem o bază curată
        app_module = load_app_in_process(args, tmp_db)
        client = InProcessClient(app_module.app)
        strict_counts = True
        today = FAKE_TODAY
        print(f"\nMeniuBot smoke test → în proces  (zi simulată: vineri {today}, bază temporară)\n")
    else:
        base = args.base.rstrip("/")
        if not args.force and not any(h in base for h in ("localhost", "127.0.0.1")):
            sys.exit(f"REFUZ: {base} nu e local. Scriptul scrie în bază. Folosește --force dacă chiar vrei.")
        today = datetime.date.today()
        if today.weekday() > 4 and not args.force_weekday:
            print(f"\033[33m!\033[0m Azi e weekend (dow={today.weekday()}). Fluxul zilnic e scurtcircuitat prin design")
            print("  (/menus/today, /menus/today/approved și /notify/pending-users întorc []).")
            print("  Rulează scriptul luni–vineri, SAU folosește --in-process (falsifică ziua, merge oricând).")
            return 0
        if today.weekday() > 4:
            print("\033[33m!\033[0m --force-weekday: rulez în weekend peste HTTP. Rutele „today” întorc [] —")
            print("  aserțiunile de meniuri/selecții VOR pica. Pentru o verificare reală: --in-process.")
        client = HttpClient(base)
        print(f"\nMeniuBot smoke test → {base}  (zi={today.weekday()}, {today})\n")

    try:
        return run(client, args)
    finally:
        if tmp_db and os.path.exists(tmp_db):
            os.unlink(tmp_db)


def run(c, args):
    # Headerul intern legitimă procesul bot.
    ih = {"X-Internal-Token": args.internal_token}
    # initData semnat pentru fiecare user de test.
    inits = [make_init_data(tg, name, args.bot_token) for tg, name in zip(TEST_TG, TEST_NAMES)]
    tgh = [{"X-Telegram-Init-Data": i} for i in inits]

    def selections_by_tg(query=""):
        st, data = c.get(f"/api/selections{query}")
        if st != 200 or not isinstance(data, list):
            return {}
        return {s["user"]["telegram_id"]: s for s in data if s.get("user")}

    # ── 1. Autentificare ───────────────────────────────────────
    print("Autentificare")
    st, data = c.post("/api/auth/login", json={"username": args.user, "password": args.password})
    check("POST /auth/login → 200", st == 200, d(st, data))
    if st != 200:
        return 1
    c.auth_headers["Authorization"] = f"Bearer {data['token']}"

    st, _ = c.get("/api/menus", headers={"Authorization": "Bearer invalid"})
    check("token invalid → 401", st == 401, f"got {st}")

    # ── 2. Meniuri și opțiuni ──────────────────────────────────
    print("\nMeniuri (două restaurante)")
    dow = FAKE_TODAY.weekday() if isinstance(c, InProcessClient) else datetime.date.today().weekday()

    st, sez = c.get(f"/api/menus?restaurant=sezatoare&day_of_week={dow}")
    check("GET /menus?restaurant=sezatoare → ≥2 meniuri", st == 200 and len(sez) >= 2, d(st, sez))
    st, andys = c.get(f"/api/menus?restaurant=andys&day_of_week={dow}")
    check("GET /menus?restaurant=andys → ≥1 meniu", st == 200 and len(andys) >= 1, d(st, andys))
    if not sez or len(sez) < 2 or not andys:
        print("  (fără meniuri nu pot continua — bază neseeded sau weekend peste HTTP)")
        return 1

    check("meniurile Andy's au opțiuni de Felul 1", all(len(m["options"]) >= 1 for m in andys),
          f"options={[len(m['options']) for m in andys]}")
    check("meniurile Șezătoare NU au opțiuni", all(len(m["options"]) == 0 for m in sez))

    st, _ = c.get("/api/menus?restaurant=pizzeria")
    check("GET /menus?restaurant=inexistent → 400", st == 400, f"got {st}")

    s1, s2, a1 = sez[0], sez[1], andys[0]

    st, m = c.put(f"/api/menus/{s1['id']}", json={
        "felul_1": "Zeamă de găină", "felul_2": "Friptură de porc"})
    check("PUT /menus/<sezatoare-1> → salvează felurile",
          st == 200 and m["felul_1"] == "Zeamă de găină", d(st, m))
    st, m = c.put(f"/api/menus/{s2['id']}", json={
        "felul_1": "Borș roșu", "felul_2": "Pilaf cu carne"})
    check("PUT /menus/<sezatoare-2> → salvează felurile",
          st == 200 and m["felul_2"] == "Pilaf cu carne", d(st, m))
    st, m = c.put(f"/api/menus/{a1['id']}", json={"felul_2": "Pilaf de casă (inclus)"})
    check("PUT /menus/<andys> → salvează Felul 2 fix",
          st == 200 and m["felul_2"] == "Pilaf de casă (inclus)", d(st, m))

    # Opțiunile de Felul 1 ale business lunch-ului Andy's.
    opt_texts = ["Supă cremă de linte", "Zeamă de casă", "Bulion de vită"]
    results = []
    for opt, text in zip(a1["options"], opt_texts):
        st, o = c.put(f"/api/menu-options/{opt['id']}", json={"text": text, "text_ru": text + " (RU)"})
        results.append(st == 200 and o["text"] == text)
    check(f"PUT /menu-options/<id> × {len(results)} → texte salvate", all(results), f"got {results}")

    st, new_opt = c.post(f"/api/menus/{a1['id']}/options",
                         json={"text": "Opțiune temporară", "text_ru": "Временно"})
    check("POST /menus/<id>/options → 201", st == 201 and new_opt.get("menu_id") == a1["id"], d(st, new_opt))
    if st == 201:
        st, _ = c.delete(f"/api/menu-options/{new_opt['id']}")
        _, andys_after = c.get(f"/api/menus?restaurant=andys&day_of_week={dow}")
        gone = all(o["id"] != new_opt["id"] for o in andys_after[0]["options"])
        check("DELETE /menu-options/<id> → 200 și opțiunea dispare", st == 200 and gone, f"got {st}")

    # Pornim de la zero: nimic aprobat.
    today_menus = sez + andys
    for m in today_menus:
        c.put(f"/api/menus/{m['id']}", json={"is_approved": False})
    st, ap = c.get("/api/menus/today/approved")
    check("GET /menus/today/approved → [] cât timp nimic nu e aprobat", ap == [], d(st, ap))

    # ── 3. Utilizatori ─────────────────────────────────────────
    print("\nUtilizatori")
    for tg, fn in zip(TEST_TG, TEST_NAMES):
        st, data = c.post("/api/users/register", headers=ih, json={
            "telegram_id": tg, "first_name": fn, "last_name": "Test", "language": "ro"})
        check(f"POST /users/register ({fn}) → 201", st == 201, d(st, data))

    st, data = c.get(f"/api/users/check/{TEST_TG[0]}", headers=ih)
    check("GET /users/check/<id> cu X-Internal-Token → registered",
          isinstance(data, dict) and data.get("registered") is True, d(st, data))

    st, data = c.get("/api/notify/pending-users", headers=ih)
    check("GET /notify/pending-users → [] fără meniu aprobat", data == [], d(st, data))

    # ── 4. Aprobare pe restaurant ──────────────────────────────
    print("\nAprobare")
    st, data = c.post("/api/menus/approve-today", json={"restaurant": "sezatoare"})
    check("POST /menus/approve-today {sezatoare} → aprobă doar Șezătoare",
          st == 200 and data.get("approved") == len(sez), d(st, data))
    check_sent("notificare „meniul e gata” la aprobare", (data or {}).get("notified"), len(TEST_TG))

    st, ap = c.get("/api/menus/today/approved")
    check("GET /menus/today/approved → doar meniurile Șezătoare",
          st == 200 and len(ap) == len(sez) and all(m["restaurant"] == "sezatoare" for m in ap),
          d(st, ap))
    st, ap = c.get("/api/menus/today/approved?restaurant=andys")
    check("GET /menus/today/approved?restaurant=andys → [] (încă neaprobat)", ap == [], d(st, ap))

    st, data = c.post("/api/menus/approve-today")
    check("POST /menus/approve-today fără body → aprobă AMBELE restaurante",
          st == 200 and data.get("approved") == len(today_menus), d(st, data))
    st, ap = c.get("/api/menus/today/approved")
    check("GET /menus/today/approved → ambele restaurante",
          len(ap) == len(today_menus) and {m["restaurant"] for m in ap} == {"sezatoare", "andys"},
          d(st, ap))

    st, data = c.get("/api/notify/pending-users", headers=ih)
    pending_ids = {u["telegram_id"] for u in data} if isinstance(data, list) else set()
    check("toți userii de test apar ca pending", set(TEST_TG) <= pending_ids, f"got {pending_ids}")

    # ── 5. Prezență ────────────────────────────────────────────
    print("\nPrezență")
    st, att_list = c.get("/api/attendance")
    att = {a["telegram_id"]: a for a in att_list} if isinstance(att_list, list) else {}
    check("GET /attendance → implicit prezent", att.get(TEST_TG[0], {}).get("is_present") is True,
          d(st, att_list))
    uid1 = att.get(TEST_TG[0], {}).get("user_id")
    c.post("/api/attendance", json={"user_id": uid1, "is_present": False})
    st, data = c.get("/api/notify/pending-users", headers=ih)
    check("absentul nu apare în pending",
          TEST_TG[0] not in {u["telegram_id"] for u in data}, d(st, data))
    c.post("/api/attendance", json={"user_id": uid1, "is_present": True})
    st, data = c.get("/api/notify/pending-users", headers=ih)
    check("revenit prezent → apare din nou în pending",
          TEST_TG[0] in {u["telegram_id"] for u in data}, d(st, data))

    # ── 6. Selecții ────────────────────────────────────────────
    # Identitatea vine din initData semnat; corpul NU conține telegram_id.
    print("\nSelecții — La Șezătoare")
    st, data = c.post("/api/selections", headers=tgh[0], json={
        "restaurant": "sezatoare", "felul1_menu_id": s1["id"], "felul2_menu_id": s2["id"]})
    check("Șezătoare: Felul 1 din meniul A + Felul 2 din meniul B → 200", st == 200, d(st, data))

    sel = selections_by_tg().get(TEST_TG[0], {})
    f1m = (sel.get("felul1_menu") or {}).get("id")
    f2m = (sel.get("felul2_menu") or {}).get("id")
    check("amestecul e păstrat: felul1_menu ≠ felul2_menu",
          f1m == s1["id"] and f2m == s2["id"] and f1m != f2m, f"felul1={f1m} felul2={f2m}")
    check("fel_selectat derivat = ambele", sel.get("fel_selectat") == "ambele", str(sel.get("fel_selectat")))
    check("restaurant = sezatoare", sel.get("restaurant") == "sezatoare", str(sel.get("restaurant")))

    st, data = c.post("/api/selections", headers=tgh[1], json={
        "restaurant": "sezatoare", "felul1_menu_id": s1["id"]})
    check("Șezătoare: doar Felul 1 → 200", st == 200, d(st, data))
    check("fel_selectat derivat = felul1",
          selections_by_tg().get(TEST_TG[1], {}).get("fel_selectat") == "felul1")

    st, data = c.post("/api/selections", headers=tgh[1], json={
        "restaurant": "sezatoare", "felul2_menu_id": s2["id"]})
    check("Șezătoare: doar Felul 2 → 200", st == 200, d(st, data))
    sel2 = selections_by_tg().get(TEST_TG[1], {})
    check("fel_selectat derivat = felul2", sel2.get("fel_selectat") == "felul2", str(sel2.get("fel_selectat")))
    check("re-trimitere → upsert, nu duplicat",
          len([1 for s in (c.get("/api/selections")[1] or []) if s["user_id"] == sel2.get("user_id")]) == 1)

    print("\nSelecții — Andy's")
    _, andys_now = c.get(f"/api/menus?restaurant=andys&day_of_week={dow}")
    a1_options = andys_now[0]["options"]
    st, data = c.post("/api/selections", headers=tgh[2], json={
        "restaurant": "andys", "felul1_menu_id": a1["id"], "felul1_option_id": a1_options[0]["id"]})
    check("Andy's: business lunch + opțiune de Felul 1 → 200", st == 200, d(st, data))

    sel3 = selections_by_tg("?restaurant=andys").get(TEST_TG[2], {})
    check("selecția Andy's poartă opțiunea aleasă",
          (sel3.get("felul1_option") or {}).get("id") == a1_options[0]["id"], str(sel3.get("felul1_option")))
    check("Andy's: Felul 2 vine automat din același meniu (ambele)",
          sel3.get("fel_selectat") == "ambele"
          and (sel3.get("felul2_menu") or {}).get("id") == a1["id"], str(sel3))

    st, data = c.post("/api/selections", headers=tgh[3], json={
        "restaurant": "andys", "felul1_menu_id": a1["id"], "felul1_option_id": a1_options[1]["id"]})
    check("Andy's: al doilea user, altă opțiune → 200", st == 200, d(st, data))

    st, data = c.post("/api/selections", headers=tgh[3], json={
        "restaurant": "andys", "felul1_menu_id": a1["id"]})
    check("Andy's FĂRĂ felul1_option_id → 400", st == 400, d(st, data))

    print("\nValidări")
    st, data = c.post("/api/selections", headers=tgh[0], json={
        "restaurant": "pizzeria", "felul1_menu_id": s1["id"]})
    check("restaurant inexistent → 400", st == 400, d(st, data))

    st, data = c.post("/api/selections", headers=tgh[0], json={"restaurant": "sezatoare"})
    check("Șezătoare fără niciun fel → 400", st == 400, d(st, data))

    st, data = c.post("/api/selections", headers=tgh[0], json={
        "restaurant": "sezatoare", "felul1_menu_id": a1["id"]})
    check("meniu Andy's trimis ca restaurant=sezatoare → 400", st == 400, d(st, data))

    st, data = c.post("/api/selections", headers=tgh[0], json={
        "restaurant": "andys", "felul1_menu_id": a1["id"], "felul1_option_id": 0})
    check("opțiune inexistentă → 400", st == 400, d(st, data))

    # Un al doilea business lunch, doar ca să avem o opțiune care NU aparține lui a1.
    st, other = c.post("/api/menus", json={
        "name": "Business Lunch temporar", "day_of_week": dow, "restaurant": "andys"})
    if st == 201 and other["options"]:
        st, data = c.post("/api/selections", headers=tgh[0], json={
            "restaurant": "andys", "felul1_menu_id": a1["id"],
            "felul1_option_id": other["options"][0]["id"]})
        check("opțiune care aparține ALTUI meniu → 400", st == 400, d(st, data))
        st, _ = c.delete(f"/api/menus/{other['id']}")
        check("DELETE /menus/<id> (meniu temporar) → 200", st == 200, f"got {st}")
    else:
        check("POST /menus (Andy's) creează opțiuni implicite", False, d(st, other))

    print("\nO singură comandă pe zi")
    st, data = c.post("/api/selections", headers=tgh[0], json={
        "restaurant": "andys", "felul1_menu_id": a1["id"], "felul1_option_id": a1_options[2]["id"]})
    check("userul de la Șezătoare trece la Andy's → 200", st == 200, d(st, data))
    st, all_sel = c.get("/api/selections")
    mine = [s for s in (all_sel or []) if s["user"]["telegram_id"] == TEST_TG[0]]
    check("GET /selections → UN SINGUR rând, restaurant=andys",
          len(mine) == 1 and mine[0]["restaurant"] == "andys",
          f"{len(mine)} rânduri: {[s['restaurant'] for s in mine]}")

    # Îl mutăm înapoi la Șezătoare: starea finală pentru rapoarte și notificări.
    st, data = c.post("/api/selections", headers=tgh[0], json={
        "restaurant": "sezatoare", "felul1_menu_id": s1["id"], "felul2_menu_id": s2["id"]})
    mine = [s for s in (c.get("/api/selections")[1] or []) if s["user"]["telegram_id"] == TEST_TG[0]]
    check("înapoi la Șezătoare → tot un singur rând",
          st == 200 and len(mine) == 1 and mine[0]["restaurant"] == "sezatoare", d(st, data))

    print("\nFără prânz / erori de identitate")
    st, data = c.post("/api/selections", headers=tgh[4], json={"fara_pranz": True})
    check("fara_pranz → 200", st == 200, d(st, data))
    check("fel_selectat = fara_pranz",
          selections_by_tg().get(TEST_TG[4], {}).get("fel_selectat") == "fara_pranz")

    unknown = {"X-Telegram-Init-Data": make_init_data(111222333444, "Ghost", args.bot_token)}
    st, data = c.post("/api/selections", headers=unknown, json={
        "restaurant": "sezatoare", "felul1_menu_id": s1["id"]})
    check("telegram_id necunoscut → 404", st == 404, d(st, data))

    st, data = c.get("/api/webapp/my-selection", headers=tgh[0])
    check("GET /webapp/my-selection → has_selection",
          isinstance(data, dict) and data.get("has_selection") is True, d(st, data))

    # ── 7. Securitate ──────────────────────────────────────────
    print("\nSecuritate")
    body = {"restaurant": "sezatoare", "felul1_menu_id": s1["id"]}

    st, _ = c.post("/api/selections", json=body, auth=False)
    check("POST /selections fără initData → 401", st == 401, f"got {st}")

    wrong_sig = {"X-Telegram-Init-Data": make_init_data(TEST_TG[0], "SmokeUnu", "wrong-bot-token")}
    st, _ = c.post("/api/selections", headers=wrong_sig, json=body, auth=False)
    check("POST /selections cu semnătură greșită → 401", st == 401, f"got {st}")

    tampered_pairs = dict(parse_qsl(inits[0]))
    tampered_pairs["user"] = json.dumps({"id": 424242, "first_name": "Hacker"})
    tampered = {"X-Telegram-Init-Data": urlencode(tampered_pairs)}
    st, _ = c.post("/api/selections", headers=tampered, json=body, auth=False)
    check("POST /selections cu initData falsificat → 401", st == 401, f"got {st}")

    st, _ = c.post("/api/users/register", auth=False, json={
        "telegram_id": 777, "first_name": "X", "last_name": "Y", "language": "ro"})
    check("POST /users/register fără X-Internal-Token → 401", st == 401, f"got {st}")

    st, _ = c.get("/api/notify/pending-users", auth=False)
    check("GET /notify/pending-users fără X-Internal-Token → 401", st == 401, f"got {st}")

    st, _ = c.get("/api/webapp/my-selection", auth=False)
    check("GET /webapp/my-selection fără header → 401", st == 401, f"got {st}")

    st, _ = c.post("/api/bot/stop", auth=False, json={"password": args.password})
    check("POST /bot/stop fără JWT → 401", st == 401, f"got {st}")

    st, _ = c.get(f"/api/users/check/{TEST_TG[1]}", headers=tgh[0], auth=False)
    check("GET /users/check/<altcuiva> cu initData propriu → 403", st == 403, f"got {st}")

    # ── 8. Rapoarte (unul per restaurant) ──────────────────────
    # Starea: u1 = Șezătoare (F1 + F2) → 2 porții; u2 = Șezătoare (doar F2) → 1 porție;
    #         u3, u4 = Andy's → 2 comenzi; u5 = fără prânz → nu apare nicăieri.
    print("\nRapoarte")
    st, rep = c.get("/api/report?restaurant=sezatoare")
    check("GET /report?restaurant=sezatoare → 200", st == 200, d(st, rep))
    if st == 200:
        check("raportul Șezătoare conține TOTAL PORȚII", "TOTAL PORȚII" in rep["report_text"])
        check("total porții Șezătoare = 3 (2 + 1)", rep["total"] == 3, f"total={rep['total']}")

    st, rep = c.get("/api/report?restaurant=andys")
    check("GET /report?restaurant=andys → 200", st == 200, d(st, rep))
    if st == 200:
        check("raportul Andy's conține TOTAL COMENZI", "TOTAL COMENZI" in rep["report_text"])
        check("total comenzi Andy's = 2", rep["total"] == 2, f"total={rep['total']}")

    st, data = c.get("/api/report")
    check("GET /report fără restaurant → 400", st == 400, d(st, data))

    # ── 9. Închiderea comenzilor ───────────────────────────────
    print("\nÎnchiderea comenzilor")
    st, _ = c.post("/api/ordering/close")
    check("POST /ordering/close → 200", st == 200, f"got {st}")

    st, data = c.get("/api/webapp/ordering-status")
    check("ordering_status → închis", data.get("ordering_open") is False, d(st, data))

    st, _ = c.post("/api/selections", headers=tgh[0], json={
        "restaurant": "sezatoare", "felul1_menu_id": s1["id"]})
    check("POST /selections cât e închis → 403", st == 403, f"got {st}")

    st, data = c.get("/api/notify/pending-users", headers=ih)
    check("pending → [] cât e închis", data == [], d(st, data))

    c.post("/api/ordering/open")
    st, data = c.get("/api/webapp/ordering-status")
    check("POST /ordering/open → redeschis", data.get("ordering_open") is True, d(st, data))

    # ── 10. Control bot ────────────────────────────────────────
    print("\nControl bot")
    st, _ = c.post("/api/bot/stop", json={"password": "parola-gresita"})
    check("bot/stop cu parolă greșită → 401", st == 401, f"got {st}")

    st, _ = c.post("/api/bot/stop", json={"password": args.password})
    check("bot/stop → oprit", st == 200, f"got {st}")
    st, data = c.get("/api/bot/status")
    check("bot/status → is_enabled=false", data.get("is_enabled") is False, d(st, data))
    st, data = c.get("/api/notify/pending-users", headers=ih)
    check("bot oprit → pending []", data == [], d(st, data))

    c.post("/api/bot/start", json={"password": args.password})
    st, data = c.get("/api/bot/status")
    check("bot/start → is_enabled=true", data.get("is_enabled") is True, d(st, data))

    c.put("/api/bot/settings", json={"is_holiday": True})
    st, data = c.get("/api/notify/pending-users", headers=ih)
    check("sărbătoare → pending []", data == [], d(st, data))
    c.put("/api/bot/settings", json={"is_holiday": False})

    # ── 11. Cele trei butoane „mâncarea a sosit" ───────────────
    # Efect secundar: dez-aprobă meniurile restaurantului notificat, deci vine la final.
    print("\nNotificare „mâncarea a sosit”")
    st, data = c.post("/api/notify/food-arrived")
    check("POST /notify/food-arrived fără body → 400", st == 400, d(st, data))
    st, data = c.post("/api/notify/food-arrived", json={"restaurant": "pizzeria"})
    check("restaurant invalid → 400", st == 400, d(st, data))

    st, data = c.post("/api/notify/food-arrived", json={"restaurant": "sezatoare"})
    check_sent("butonul Șezătoare → notifică doar cei 2 de acolo", (data or {}).get("count"), 2)
    st, ap = c.get("/api/menus/today/approved")
    check("după notificare, meniurile Șezătoare sunt dez-aprobate",
          all(m["restaurant"] == "andys" for m in ap), d(st, ap))

    st, data = c.post("/api/notify/food-arrived", json={"restaurant": "andys"})
    check_sent("butonul Andy's → notifică doar cei 2 de acolo", (data or {}).get("count"), 2)

    st, data = c.post("/api/notify/food-arrived", json={"restaurant": "all"})
    check_sent("butonul „toți” → notifică toți cei 4 (fara_pranz sărit)", (data or {}).get("count"), 4)

    st, ap = c.get("/api/menus/today/approved")
    check("după „toți”, niciun meniu nu mai e aprobat", ap == [], d(st, ap))

    # ── 12. Curățenie ──────────────────────────────────────────
    # SmokeUnu a fost marcat absent mai sus, deci are un rând în `attendance` — exact
    # cazul care făcea DELETE /users/<id> să dea 500 (P2.3, acum reparat: delete_user()
    # curăță și `attendance`). Ștergerea lui e paza contra regresiei.
    print("\nCurățenie")
    st, users = c.get("/api/users")
    for u in users or []:
        if u["telegram_id"] in TEST_TG:
            st, _ = c.delete(f"/api/users/{u['id']}")
            check(f"DELETE /users/{u['id']} ({u['first_name']})", st == 200,
                  "vezi P2.3 — attendance.user_id NOT NULL" if st == 500 else f"got {st}")

    print(f"\n{'─' * 52}")
    print(f"  \033[32m{ok_count} trecute\033[0m, " +
          (f"\033[31m{fail_count} picate\033[0m" if fail_count else "0 picate"))
    print(f"{'─' * 52}\n")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
