---
name: meniubot-verify
description: Verifică end-to-end fluxul zilnic MeniuBot pe cele două restaurante (login → aprobare meniu → selecții La Șezătoare / Andy's → rapoarte → cele trei butoane „mâncarea a sosit" → închidere comenzi → stop bot), fie prin HTTP pe un backend pornit, fie în proces, cu ziua falsificată. Folosește-l după orice modificare în backend/app.py, models.py, calculations.py sau scheduler.py, înainte de commit sau deploy. Se declanșează la „verifică", „testează că merge", „nu am stricat nimic", „smoke test", „merge fluxul?".
---

# MeniuBot — verificare end-to-end

Rulează fluxul real prin API, nu doar testele unitare. `test_calculations.py` + `test_auth.py`
acoperă calculele și autentificarea — și **nimic altceva**: nici un endpoint, nici aprobarea, nici
filtrarea reminderelor, nici combinația de restaurante. Acest skill acoperă restul.

**96 de aserțiuni** pe lanțul complet: autentificare → meniuri și opțiuni Andy's → aprobare pe
restaurant → înregistrare utilizatori → prezență → selecții la La Șezătoare și la Andy's (cu toate
validările) → securitatea modelului de auth → cele două rapoarte → închiderea comenzilor → stopul de
urgență → cele trei butoane „mâncarea a sosit" → curățenie.

## Modelul cu două restaurante (ce testează, de fapt)

- **La Șezătoare** — combinație liberă. Felul 1 dintr-un meniu **și** Felul 2 din **alt** meniu, sau
  doar unul dintre ele. Corpul cererii e `{"restaurant":"sezatoare","felul1_menu_id":A,"felul2_menu_id":B}`
  (oricare din cele două id-uri poate lipsi, dar nu amândouă).
- **Andy's** — un business lunch; Felul 2 e **fix și inclus**, Felul 1 se alege **obligatoriu** dintre
  opțiunile meniului: `{"restaurant":"andys","felul1_menu_id":M,"felul1_option_id":O}`.
- **O singură comandă pe zi**, dintr-un singur restaurant — upsert pe `(user_id, date)`. Dacă userul
  trece de la Șezătoare la Andy's, rândul e înlocuit, nu adăugat.
- **Maxi/Standard nu mai există.** Fiecare fel ales = 1 porție. `GET /api/selections/alerts` a fost
  ștearsă odată cu împerecherea, deci nu mai există aserțiuni de „Felul 1 nepereche".
- **Rapoarte separate.** `GET /api/report?restaurant=…` — parametrul e **obligatoriu** (fără el → 400).
  Șezătoare încheie cu `TOTAL PORȚII`, Andy's cu `TOTAL COMENZI`.
- **Trei butoane** de sosire: `POST /api/notify/food-arrived` cu `{"restaurant": "sezatoare"|"andys"|"all"}`
  — obligatoriu (fără el → 400).

Autentificarea e **neschimbată**: `X-Telegram-Init-Data` (initData semnat HMAC-SHA256 cu tokenul
botului, construit de `make_init_data()`) pentru Mini App, `X-Internal-Token` pentru procesul bot,
JWT admin pentru panou. Secțiunea „Securitate" verifică explicit că fără header, cu semnătură greșită,
cu initData falsificat sau cu initData al altui user se întorc 401/403.

## Două moduri de rulare

### A. `--in-process` — recomandat, merge oricând (inclusiv în weekend)

Scriptul importă `backend/app.py`, îi înlocuiește `today_moldova()` cu o **vineri fixă
(2026-07-10)** și `send_telegram_message()` cu un lambda care întoarce `True`, apoi rulează aceleași
aserțiuni prin `app.test_client()`, pe o bază SQLite temporară pe care o șterge singur la final.

```bash
python3 .claude/skills/meniubot-verify/scripts/smoke.py --in-process
```

Nu are nevoie de server pornit și nu atinge nicio bază reală. Variabilele de mediu
(`SECRET_KEY`, `INTERNAL_API_TOKEN`, `TELEGRAM_BOT_TOKEN`, `DATABASE_URL`, `ADMIN_*`) sunt setate de
script **înainte** de `import app` — obligatoriu, fiindcă `app.py` ridică `RuntimeError` la import
fără secrete și tot la import rulează `db.create_all()`, migrațiile și seed-ul.

Fiindcă trimiterea către Telegram e simulată, contoarele sunt **deterministe**: `notified` de la
aprobare și `count` de la „mâncarea a sosit" sunt verificate exact.

Dacă dependențele nu-s instalate în sistem, fă un venv:

```bash
SP="$CLAUDE_SCRATCHPAD"
python3 -m venv "$SP/venv"
"$SP/venv/bin/pip" install -q -r backend/requirements.txt
"$SP/venv/bin/python" .claude/skills/meniubot-verify/scripts/smoke.py --in-process
```

### B. HTTP — lovește un backend deja pornit

Folosește-l când vrei să verifici un server real (rutare, nginx, gunicorn), nu doar logica.

```bash
rm -f "$SP/test.db"
cd backend
DATABASE_URL="sqlite:///$SP/test.db" \
SECRET_KEY=0123456789abcdef0123456789abcdef \
INTERNAL_API_TOKEN=test-internal-token \
TELEGRAM_BOT_TOKEN=test-bot-token \
ADMIN_USERNAME=admin ADMIN_PASSWORD=admin FLASK_PORT=5099 \
  "$SP/venv/bin/python" run.py > "$SP/server.log" 2>&1 &

for i in $(seq 1 20); do
  curl -sf http://localhost:5099/api/bot/status >/dev/null 2>&1 && break
  sleep 1
done

"$SP/venv/bin/python" .claude/skills/meniubot-verify/scripts/smoke.py \
  --base http://localhost:5099 --bot-token test-bot-token --internal-token test-internal-token
```

`--bot-token` și `--internal-token` trebuie să fie **exact** `TELEGRAM_BOT_TOKEN` și
`INTERNAL_API_TOKEN` ale serverului, altfel semnătura initData nu se verifică și selecțiile pică cu
401. Implicitele scriptului sunt tocmai `test-bot-token` și `test-internal-token`.

Două limite ale modului HTTP:

- **Weekend.** Sâmbăta și duminica `/menus/today`, `/menus/today/approved` și `/notify/pending-users`
  întorc `[]` prin design. Scriptul detectează asta, explică de ce și iese cu 0. Cu `--force-weekday`
  rulează oricum, dar aserțiunile de meniuri și selecții vor pica — **folosește `--in-process`**, e
  exact motivul pentru care există.
- **Contoarele de mesaje.** Serverul chiar încearcă să sune Telegram cu un token fals, deci nu trimite
  nimic și întoarce `notified: 0` / `count: 0`. Peste HTTP scriptul verifică doar că valoarea e un
  întreg; egalitatea exactă (2 / 2 / 4) o verifică doar `--in-process`.

## Reguli

**Niciodată pe producție.** Scriptul creează utilizatori, scrie selecții, dez-aprobă meniuri, închide
comenzile și oprește botul. În modul HTTP refuză un host care nu conține `localhost` sau `127.0.0.1`,
în afară de cazul cu `--force`. Nu folosi `--force` decât dacă utilizatorul cere explicit.
Modul `--in-process` e sigur prin construcție: bază temporară, Telegram simulat.

**Bază de date temporară.** Nu porni backend-ul pe baza reală: `DATABASE_URL` către un fișier din
scratchpad. La import, `app.py` rulează `db.create_all()`, migrațiile și `seed_default_menus()`, deci
baza goală primește automat meniurile săptămânii (Lunch 1 + Lunch 2 la Șezătoare, Business Lunch 1 cu
3 opțiuni la Andy's, pentru fiecare zi Luni–Vineri). Nu semăna nimic manual.

## Cum citești rezultatul

Ieșire `0` = totul verde. În modul HTTP, orice `✗` → **citește `$SP/server.log`** pentru traceback-ul
real: un `500` apare în script doar ca un cod de stare, cauza e în log.

```bash
grep -iE "error|traceback|IntegrityError" "$SP/server.log" | head
```

## Starea de referință

Pe o bază curată, `smoke.py --in-process` dă:

**96 trecute, 0 picate** (cod de ieșire 0) — cifre măsurate pe repo-ul curent, nu inventate.

Orice `✗` este o regresie a ta. Nu mai există eșecuri „așteptate": bug-ul **P2.3**
(`DELETE /users/<id>` dădea 500 pentru orice user cu rând în `attendance`) a fost reparat —
`delete_user()` curăță acum și `attendance`. Secțiunea „Curățenie" îl marchează pe SmokeUnu absent
tocmai ca să reproducă acel caz: dacă cineva scoate curățarea, testul redevine roșu.

Distribuția aserțiunilor pe secțiuni: autentificare 2 · meniuri și opțiuni 12 · utilizatori 7 ·
aprobare 7 · prezență 3 · selecții Șezătoare 9 · selecții Andy's 5 · validări 6 · o comandă pe zi 3 ·
fără prânz și identitate 4 · securitate 8 · rapoarte 7 · închiderea comenzilor 5 · control bot 6 ·
cele trei butoane 7 · curățenie 5.

Starea finală a celor 5 useri de test, pe care se sprijină rapoartele și contoarele:
SmokeUnu = Șezătoare (Felul 1 din Lunch 1 + Felul 2 din Lunch 2 → 2 porții), SmokeDoi = Șezătoare
(doar Felul 2 → 1 porție), SmokeTrei și SmokePatru = Andy's (2 comenzi, opțiuni diferite),
SmokeCinci = fără prânz (nu apare în niciun raport și nu primește nicio notificare).
De aici: raport Șezătoare `total = 3`, raport Andy's `total = 2`, butoane `2 / 2 / 4`.

## Ce nu acoperă

Conversația botului (`bot.py` — `/start`, `/menu`, `/guide`), joburile de scheduler, Mini App-ul, și
trimiterea efectivă de mesaje Telegram (în `--in-process` e simulată prin construcție). Pentru astea
nu există automatizare — verifică manual sau extinde scriptul.

## Când extinzi scriptul

Adaugi un endpoint nou → adaugi o aserțiune. Tiparul e `check(eticheta, conditie, detaliu)`, iar
pentru contoarele de mesaje `check_sent(eticheta, valoare, asteptat)` (exact doar în proces).

Nu chema `requests` direct: toate cererile trec prin clientul uniform (`c.get/.post/.put/.delete` →
`(status_code, json)`), ca aceeași aserțiune să meargă și prin HTTP, și prin `test_client`. Pentru
testele de securitate folosește `auth=False` (cerere fără JWT).

Ordinea secțiunilor nu e arbitrară: „mâncarea a sosit" **dez-aprobă** meniurile restaurantului
notificat, deci stă la final; prezența și pending-users stau înainte de selecții, fiindcă un user care
a ales deja nu mai apare niciodată ca pending. Curăță după tine în secțiunea „Curățenie" și ține
scriptul rulabil pe o bază goală, fără fixture-uri externe.
</content>
