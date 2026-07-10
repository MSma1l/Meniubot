#!/usr/bin/env python3
"""Smoke test end-to-end pentru fluxul zilnic MeniuBot.

Exercită lanțul real: login → editează meniu → aprobă → înregistrează useri →
selecții → alerte nepereche → raport → prezență → închide comenzi → control bot.
Include și testele de securitate pentru noul model de autentificare (initData
Telegram semnat + token intern între bot și API).

Scrie în baza de date. Refuză să pornească pe un host non-local fără --force.

    python smoke.py [--base http://localhost:5000] [--user admin] [--password admin]
                    [--bot-token test-bot-token] [--internal-token test-internal-token]

Iese cu 0 dacă toate verificările trec, 1 altfel.
"""
import argparse
import hashlib
import hmac
import json
import sys
import time
from datetime import date
from urllib.parse import parse_qsl, urlencode

import requests

TEST_TG_1 = 999000001
TEST_TG_2 = 999000002

ok_count = 0
fail_count = 0


def check(label, cond, detail=""):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  \033[32m✓\033[0m {label}")
    else:
        fail_count += 1
        print(f"  \033[31m✗\033[0m {label}" + (f"\n      {detail}" if detail else ""))


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5000")
    ap.add_argument("--user", default="admin")
    ap.add_argument("--password", default="admin")
    ap.add_argument("--bot-token", default="test-bot-token",
                    help="tokenul botului cu care se semnează initData (trebuie egal cu TELEGRAM_BOT_TOKEN al serverului)")
    ap.add_argument("--internal-token", default="test-internal-token",
                    help="secretul intern bot↔API (trebuie egal cu INTERNAL_API_TOKEN al serverului)")
    ap.add_argument("--force", action="store_true", help="permite rularea pe host non-local")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    if not args.force and not any(h in base for h in ("localhost", "127.0.0.1")):
        sys.exit(f"REFUZ: {base} nu e local. Scriptul scrie în bază. Folosește --force dacă chiar vrei.")

    api = f"{base}/api"
    s = requests.Session()

    # Headerul intern legitimă procesul bot. Îl folosim explicit pe rutele care
    # acum îl cer (register, pending-users, check_user pe calea internă).
    ih = {"X-Internal-Token": args.internal_token}

    # initData semnat pentru fiecare user de test.
    init1 = make_init_data(TEST_TG_1, "SmokeUnu", args.bot_token)
    init2 = make_init_data(TEST_TG_2, "SmokeDoi", args.bot_token)
    tg1_headers = {"X-Telegram-Init-Data": init1}
    tg2_headers = {"X-Telegram-Init-Data": init2}

    today = date.today()
    dow = today.weekday()
    if dow > 4:
        print(f"\033[33m!\033[0m Azi e weekend (dow={dow}). Fluxul zilnic e scurtcircuitat prin design")
        print("  (/menus/today, /menus/today/approved și /notify/pending-users întorc []).")
        print("  Rulează scriptul luni–vineri.")
        return 0

    print(f"\nMeniuBot smoke test → {base}  (zi={dow}, {today})\n")

    # ── 1. Auth ────────────────────────────────────────────────
    print("Autentificare")
    r = s.post(f"{api}/auth/login", json={"username": args.user, "password": args.password})
    check("POST /auth/login → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")
    if r.status_code != 200:
        return 1
    token = r.json()["token"]
    s.headers["Authorization"] = f"Bearer {token}"

    r = s.get(f"{api}/menus", headers={"Authorization": "Bearer invalid"})
    check("token invalid → 401", r.status_code == 401, f"got {r.status_code}")

    # ── 2. Meniuri ─────────────────────────────────────────────
    print("\nMeniuri")
    r = s.get(f"{api}/menus?day_of_week={dow}")
    menus = r.json()
    check(f"GET /menus?day_of_week={dow} → meniuri există", len(menus) > 0, f"got {len(menus)}")
    if not menus:
        return 1
    m0 = menus[0]

    r = s.put(f"{api}/menus/{m0['id']}", json={"felul_1": "Ciorbă de test", "felul_2": "Friptură de test"})
    check("PUT /menus/<id> → salvează conținut", r.status_code == 200 and r.json()["felul_1"] == "Ciorbă de test")

    # pornim de la zero: nimic aprobat
    for m in menus:
        s.put(f"{api}/menus/{m['id']}", json={"is_approved": False})

    r = s.get(f"{api}/menus/today/approved")
    check("GET /menus/today/approved → [] cât timp nimic nu e aprobat", r.json() == [], f"got {r.json()}")

    r = s.get(f"{api}/notify/pending-users", headers=ih)
    check("GET /notify/pending-users → [] fără meniu aprobat", r.json() == [], f"got {len(r.json())} useri")

    r = s.post(f"{api}/menus/approve-today")
    check("POST /menus/approve-today → aprobă", r.status_code == 200 and r.json()["approved"] > 0)

    r = s.get(f"{api}/menus/today/approved")
    approved = r.json()
    check("GET /menus/today/approved → meniurile apar", len(approved) == len(menus), f"{len(approved)} vs {len(menus)}")

    # ── 3. Utilizatori ─────────────────────────────────────────
    # Înregistrarea vine de la procesul bot → cere X-Internal-Token.
    print("\nUtilizatori")
    for tg, fn, ln in ((TEST_TG_1, "SmokeUnu", "Test"), (TEST_TG_2, "SmokeDoi", "Test")):
        r = s.post(f"{api}/users/register", headers=ih, json={
            "telegram_id": tg, "first_name": fn, "last_name": ln, "language": "ro"})
        check(f"POST /users/register ({fn}) → 201", r.status_code == 201, f"got {r.status_code}: {r.text[:120]}")

    # check_user pe calea internă (botul poate citi pe oricine)
    r = s.get(f"{api}/users/check/{TEST_TG_1}", headers=ih)
    check("GET /users/check/<id> cu X-Internal-Token → registered", r.json().get("registered") is True,
          f"got {r.status_code}: {r.text[:120]}")

    r = s.get(f"{api}/notify/pending-users", headers=ih)
    pending_ids = {u["telegram_id"] for u in r.json()}
    check("userii noi apar ca pending", TEST_TG_1 in pending_ids and TEST_TG_2 in pending_ids)

    # ── 4. Selecții ────────────────────────────────────────────
    # Identitatea vine din initData semnat; corpul NU mai conține telegram_id.
    print("\nSelecții")
    r = s.post(f"{api}/selections", headers=tg1_headers, json={
        "menu_id": m0["id"], "fel_selectat": "ambele"})
    check("POST /selections (ambele) → ok", r.status_code == 200, f"got {r.status_code}: {r.text[:120]}")

    r = s.post(f"{api}/selections", headers=tg1_headers, json={
        "menu_id": m0["id"], "fel_selectat": "felul1"})
    check("POST /selections din nou → upsert, nu duplicat", r.status_code == 200)

    r = s.get(f"{api}/selections")
    mine = [x for x in r.json() if x["user"]["telegram_id"] == TEST_TG_1]
    check("GET /selections → exact 1 rând pentru user", len(mine) == 1, f"got {len(mine)}")
    check("selecția reflectă ultimul upsert", bool(mine) and mine[0]["fel_selectat"] == "felul1")

    r = s.get(f"{api}/webapp/my-selection", headers=tg1_headers)
    check("GET /webapp/my-selection → has_selection", r.json().get("has_selection") is True,
          f"got {r.status_code}: {r.text[:120]}")

    r = s.post(f"{api}/selections", headers=tg1_headers, json={
        "menu_id": m0["id"], "fel_selectat": "inexistent"})
    check("fel_selectat invalid → 400", r.status_code == 400, f"got {r.status_code}")

    # initData semnat pentru un telegram_id neînregistrat → 404
    unknown_headers = {"X-Telegram-Init-Data": make_init_data(111222333444, "Ghost", args.bot_token)}
    r = s.post(f"{api}/selections", headers=unknown_headers, json={
        "menu_id": m0["id"], "fel_selectat": "ambele"})
    check("telegram_id necunoscut → 404", r.status_code == 404, f"got {r.status_code}")

    # ── 4b. Securitate: autentificarea nu se lasă păcălită ─────
    print("\nSecuritate")
    # POST /selections FĂRĂ header initData → 401
    r = requests.post(f"{api}/selections", json={"menu_id": m0["id"], "fel_selectat": "ambele"})
    check("POST /selections fără initData → 401", r.status_code == 401, f"got {r.status_code}")

    # POST /selections cu initData semnat cu bot token GREȘIT → 401
    wrong_sig = {"X-Telegram-Init-Data": make_init_data(TEST_TG_1, "SmokeUnu", "wrong-bot-token")}
    r = requests.post(f"{api}/selections", headers=wrong_sig, json={"menu_id": m0["id"], "fel_selectat": "ambele"})
    check("POST /selections cu semnătură greșită → 401", r.status_code == 401, f"got {r.status_code}")

    # POST /selections cu initData FALSIFICAT (schimb user după semnare) → 401
    tampered_pairs = dict(parse_qsl(init1))
    tampered_pairs["user"] = json.dumps({"id": 424242, "first_name": "Hacker"})
    tampered = {"X-Telegram-Init-Data": urlencode(tampered_pairs)}
    r = requests.post(f"{api}/selections", headers=tampered, json={"menu_id": m0["id"], "fel_selectat": "ambele"})
    check("POST /selections cu initData falsificat → 401", r.status_code == 401, f"got {r.status_code}")

    # POST /users/register fără X-Internal-Token → 401
    r = requests.post(f"{api}/users/register", json={
        "telegram_id": 777, "first_name": "X", "last_name": "Y", "language": "ro"})
    check("POST /users/register fără X-Internal-Token → 401", r.status_code == 401, f"got {r.status_code}")

    # GET /notify/pending-users fără X-Internal-Token → 401
    r = requests.get(f"{api}/notify/pending-users")
    check("GET /notify/pending-users fără X-Internal-Token → 401", r.status_code == 401, f"got {r.status_code}")

    # GET /webapp/my-selection fără header → 401
    r = requests.get(f"{api}/webapp/my-selection")
    check("GET /webapp/my-selection fără header → 401", r.status_code == 401, f"got {r.status_code}")

    # POST /bot/stop fără JWT → 401
    r = requests.post(f"{api}/bot/stop", json={"password": args.password})
    check("POST /bot/stop fără JWT → 401", r.status_code == 401, f"got {r.status_code}")

    # GET /users/check/<id_altcuiva> cu initData al MEU → 403
    r = requests.get(f"{api}/users/check/{TEST_TG_2}", headers=tg1_headers)
    check("GET /users/check/<altcuiva> cu initData propriu → 403", r.status_code == 403, f"got {r.status_code}")

    # ── 5. Alerta „Felul 1 nepereche" ──────────────────────────
    print("\nAlerte nepereche")
    r = s.get(f"{api}/selections/alerts")
    alerts = [a for a in r.json() if a["menu"] == m0["name"]]
    check("1× felul1 → alertă nepereche", len(alerts) == 1 and alerts[0]["count"] == 1, f"got {r.json()}")

    s.post(f"{api}/selections", headers=tg2_headers, json={"menu_id": m0["id"], "fel_selectat": "felul1"})
    r = s.get(f"{api}/selections/alerts")
    alerts = [a for a in r.json() if a["menu"] == m0["name"]]
    check("2× felul1 → alerta dispare (se împerechează)", len(alerts) == 0, f"got {r.json()}")

    # ── 6. Raport ──────────────────────────────────────────────
    print("\nRaport")
    r = s.get(f"{api}/report")
    check("GET /report → 200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
    if r.status_code == 200:
        rep = r.json()
        p = rep["portions"].get(m0["name"], {})
        check("2× felul1 → 1 porție Maxi", p.get("maxi") == 1, f"portions={p}")
        check("0 porții Standard", p.get("standard") == 0, f"portions={p}")
        check("report_text conține TOTAL PORȚII", "TOTAL PORȚII" in rep["report_text"])

    # ── 7. Prezență ────────────────────────────────────────────
    print("\nPrezență")
    r = s.get(f"{api}/attendance")
    att = {a["telegram_id"]: a for a in r.json()}
    check("GET /attendance → implicit prezent", att.get(TEST_TG_1, {}).get("is_present") is True)

    uid = att[TEST_TG_1]["user_id"]
    s.post(f"{api}/attendance", json={"user_id": uid, "is_present": False})
    r = s.get(f"{api}/notify/pending-users", headers=ih)
    check("absentul nu apare în pending", TEST_TG_1 not in {u["telegram_id"] for u in r.json()})
    s.post(f"{api}/attendance", json={"user_id": uid, "is_present": True})

    # ── 8. Închiderea comenzilor ───────────────────────────────
    print("\nÎnchiderea comenzilor")
    r = s.post(f"{api}/ordering/close")
    check("POST /ordering/close → 200", r.status_code == 200, f"got {r.status_code}")

    r = s.get(f"{api}/webapp/ordering-status")
    check("ordering_status → închis", r.json().get("ordering_open") is False)

    r = s.post(f"{api}/selections", headers=tg1_headers, json={
        "menu_id": m0["id"], "fel_selectat": "felul2"})
    check("POST /selections cât e închis → 403", r.status_code == 403, f"got {r.status_code}")

    r = s.get(f"{api}/notify/pending-users", headers=ih)
    check("pending → [] cât e închis", r.json() == [])

    s.post(f"{api}/ordering/open")
    r = s.get(f"{api}/webapp/ordering-status")
    check("POST /ordering/open → redeschis", r.json().get("ordering_open") is True)

    # ── 9. Control bot ─────────────────────────────────────────
    # bot/stop și bot/start cer acum JWT admin (headerul Authorization e deja pe
    # sesiune) ȘI parola în corp.
    print("\nControl bot")
    r = s.post(f"{api}/bot/stop", json={"password": "parola-gresita"})
    check("bot/stop cu parolă greșită → 401", r.status_code == 401, f"got {r.status_code}")

    r = s.post(f"{api}/bot/stop", json={"password": args.password})
    check("bot/stop → oprit", r.status_code == 200)
    r = s.get(f"{api}/bot/status")
    check("bot/status → is_enabled=false", r.json()["is_enabled"] is False)
    r = s.get(f"{api}/notify/pending-users", headers=ih)
    check("bot oprit → pending []", r.json() == [])

    s.post(f"{api}/bot/start", json={"password": args.password})
    r = s.get(f"{api}/bot/status")
    check("bot/start → is_enabled=true", r.json()["is_enabled"] is True)

    s.put(f"{api}/bot/settings", json={"is_holiday": True})
    r = s.get(f"{api}/notify/pending-users", headers=ih)
    check("sărbătoare → pending []", r.json() == [])
    s.put(f"{api}/bot/settings", json={"is_holiday": False})

    # ── 10. Curățenie ──────────────────────────────────────────
    # NOTĂ: DELETE /users/<id> dă 500 pentru orice user cu rând în `attendance`
    # (P2.3 din docs/09-probleme-cunoscute.md). SmokeUnu a fost marcat absent mai sus,
    # deci ștergerea lui EȘUEAZĂ până se repară bug-ul. Asta e intenționat: testul
    # devine verde exact când bug-ul e reparat.
    print("\nCurățenie")
    r = s.get(f"{api}/users")
    for u in r.json():
        if u["telegram_id"] in (TEST_TG_1, TEST_TG_2):
            rr = s.delete(f"{api}/users/{u['id']}")
            check(f"DELETE /users/{u['id']} ({u['first_name']})", rr.status_code == 200,
                  "vezi P2.3 — attendance.user_id NOT NULL" if rr.status_code == 500 else f"got {rr.status_code}")

    print(f"\n{'─' * 52}")
    print(f"  \033[32m{ok_count} trecute\033[0m, " +
          (f"\033[31m{fail_count} picate\033[0m" if fail_count else "0 picate"))
    print(f"{'─' * 52}\n")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())
