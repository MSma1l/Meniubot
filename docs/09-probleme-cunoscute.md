# 09 — Probleme cunoscute

Audit al codului la data de 2026-07-10. Fiecare problemă are referință la fișier și linie.

> **Actualizare 2026-07-10:** toate cele patru probleme P0 au fost închise, plus P1.1, P1.2, P2.4 și
> parțial P1.3 și P1.5.
>
> **Actualizare 2026-07-12** (trecerea pe două restaurante): închise și **P2.2** (raportul crăpa după
> ștergerea unui meniu), **P2.3** (nu se putea șterge un user marcat absent) și **P2.9** (seed
> duplicat). Toate trei confirmate experimental, înainte și după.
>
> Vezi nota `✅ REPARAT` de sub fiecare titlu — descrierea istorică e păstrată pentru context. Restul
> documentului descrie codul **așa cum e**, nereparat.

Problemele marcate **confirmat experimental** au fost reproduse rulând backend-ul pe o bază de test
și lovind API-ul. Restul sunt citite din cod.

## Probleme apărute odată cu cele două restaurante

- **Reset-ul nu golește opțiunile Andy's.** `POST /api/menus/reset-content` golește textele meniurilor,
  dar `menu_options` supraviețuiesc. Opțiunile de Felul 1 de săptămâna trecută rămân afișate până când
  adminul le rescrie. (De discutat: poate e chiar comportamentul dorit — se reportează, ca structura.)
- **Fără constrângere de unicitate** pe `(restaurant, day_of_week, week_start_date, name)`. Un
  `POST /api/menus` repetat creează duplicate.
- **Un business lunch fără opțiuni e o fundătură.** Dacă adminul șterge toate opțiunile de Felul 1,
  meniul apare în Mini App dar nu se poate comanda nimic din el. Panoul avertizează, backend-ul nu
  împiedică.

Pentru un checklist executabil înainte de deploy: `/meniubot-preflight`.

---

## P0 — Securitate critică

Exploatabile de oricine are adresa serverului. Un angajat cu Telegram poate afla `telegram_id`-ul
colegilor din `/api/notify/pending-users`, care e public.

### P0.1 — `SECRET_KEY` implicit este public

> ✅ **REPARAT** la 2026-07-10. `app.py` ridică `RuntimeError` la pornire dacă `SECRET_KEY` lipsește,
> e gol, sau e una din valorile respinse explicit (`dev-secret-key`, `your_secret_key`). Nu mai există
> niciun fallback random. În `docker-compose.yml` se folosește `${SECRET_KEY:?...}`, deci `docker
> compose up` eșuează cu mesaj clar dacă `.env` n-o definește.

[`docker-compose.yml:9`](../docker-compose.yml) · [`app.py:22`](../backend/app.py)

```yaml
- SECRET_KEY=${SECRET_KEY:-dev-secret-key}
```

Dacă `.env` nu definește `SECRET_KEY`, JWT-urile sunt semnate cu șirul `dev-secret-key`, care e
scris în repo. Oricine poate forja un token de administrator și poate apela orice endpoint `🔒`.

În `app.py` fallback-ul e `secrets.token_hex(32)` — random la fiecare pornire. Asta invalidează
sesiunile la restart, iar sub gunicorn cu mai mulți workeri fiecare worker are altă cheie, deci
autentificarea eșuează aleatoriu.

**Reparație:** elimină ambele fallback-uri, oprește pornirea dacă lipsește.

### P0.2 — Identitatea utilizatorului nu e verificată

> ✅ **REPARAT** la 2026-07-10.

[`app.py:375`](../backend/app.py) · [`static/webapp/index.html:337`](../backend/static/webapp/index.html)

`POST /api/selections` este public și primește `telegram_id` în corpul cererii. Nimic nu verifică
faptul că apelantul **este** acel utilizator.

```bash
# suprascrie comanda oricui, dacă îi știi telegram_id-ul
curl -X POST https://.../meniubot/api/selections \
  -H 'Content-Type: application/json' \
  -d '{"telegram_id": 123456789, "menu_id": 3, "fel_selectat": "fara_pranz"}'
```

Mini App-ul citește identitatea din `tg.initDataUnsafe.user.id`. Numele câmpului spune de ce:
**`initDataUnsafe` nu e verificat**. Telegram trimite în paralel `tg.initData` — un șir semnat
HMAC-SHA256 cu token-ul botului, exact pentru validare pe server. Nu e folosit nicăieri.

**Soluția implementată:** [`backend/auth.py`](../backend/auth.py) reverifică semnătura HMAC-SHA256 a
`initData`-ului cu `TELEGRAM_BOT_TOKEN`. Mini App-ul trimite șirul semnat în headerul
`X-Telegram-Init-Data`; decoratorul `@require_telegram` îl validează (semnătură, vechime, `auth_date`)
și pune utilizatorul verificat în `g.telegram_user`. Handlerele citesc `g.telegram_user["id"]` și
ignoră complet orice `telegram_id` din corp. Endpoint-urile chemate de bot folosesc `@require_internal`
(headerul `X-Internal-Token`). 15 teste în [`backend/test_auth.py`](../backend/test_auth.py) acoperă
semnături valide/invalide, șiruri expirate, malformate și lipsă.

### P0.3 — Oprirea botului e un endpoint public

> ✅ **REPARAT** la 2026-07-10. `POST /api/bot/stop` și `POST /api/bot/start` cer acum `@token_required`
> (JWT admin). Parola din corp rămâne ca a doua confirmare, comparată în timp constant cu
> `hmac.compare_digest`. Rate limiting-ul tot **lipsește** (vezi P1.5).

[`app.py:673`](../backend/app.py), [`app.py:693`](../backend/app.py)

`POST /api/bot/stop` și `POST /api/bot/start` **nu** au `@token_required`. Singura apărare e
`ADMIN_PASSWORD` trimisă în corp, comparată cu `!=` (nu în timp constant) și fără rate limiting.

Un atacator poate ghici parola nelimitat, sau — cu parola implicită `admin` — oprește toate
notificările instantaneu. Nimeni nu mai primește reminder și nici „mâncarea a sosit".

**Reparație:** adaugă `@token_required`, păstrează parola ca a doua confirmare, compară cu
`secrets.compare_digest`, adaugă rate limiting.

### P0.4 — Oricine poate suprascrie datele oricărui utilizator

> ✅ **REPARAT** la 2026-07-10. `POST /api/users/register` cere acum `@require_internal`
> (`X-Internal-Token`) — doar procesul bot îl poate apela, nu mai e public.

[`app.py:452`](../backend/app.py)

`POST /api/users/register` e public și face upsert pe `telegram_id`. Un apelant poate schimba
`first_name`, `last_name` și `language` pentru orice utilizator existent.

**Reparație:** aceeași ca la P0.2 — leagă-l de `initData` validat.

---

## P1 — Securitate

### P1.1 — IDOR: citirea comenzii altcuiva

> ✅ **REPARAT** la 2026-07-10. `GET /api/webapp/my-selection` cere acum `@require_telegram`; query
> param-ul `telegram_id` a fost eliminat. Utilizatorul e luat din `g.telegram_user["id"]`, deci poți
> citi doar propria alegere.

[`app.py:953`](../backend/app.py)

`GET /api/webapp/my-selection?telegram_id=<oricine>` întoarce alegerea oricărui utilizator.

### P1.2 — Scurgere de `telegram_id`-uri

> ✅ **REPARAT** la 2026-07-10. `GET /api/notify/pending-users` cere acum `@require_internal`
> (`X-Internal-Token`) — exact tokenul de serviciu partajat cu botul propus mai jos. Nu mai e public.

[`app.py:620`](../backend/app.py)

`GET /api/notify/pending-users` e public și întoarce lista completă de `telegram_id` + limbă.
Este exact materia primă pentru P0.2 și P0.4.

Este public fiindcă îl consumă procesul bot. Botul rulează însă pe rețeaua internă Docker — nu are
nevoie de acces public.

**Reparație:** un token de serviciu partajat între backend și bot, sau restricționare pe rețeaua internă.

### P1.3 — Enumerarea utilizatorilor

> ✅ **REPARAT parțial** la 2026-07-10. `GET /api/users/check/<telegram_id>` nu mai e public: cere fie
> `initData` valid (și doar pentru propriul `id`, altfel `403`), fie `X-Internal-Token` (botul). Nu mai
> poate fi folosit anonim pentru enumerare.

[`app.py:476`](../backend/app.py)

`GET /api/users/check/<telegram_id>` e public și întoarce obiectul `User` complet, inclusiv
`username` și `language`.

### P1.4 — CORS deschis către orice origine

[`app.py:24`](../backend/app.py) — `CORS(app)`, fără restricții, pe toate rutele.

Token-ul stă în `localStorage`, deci nu e un vector CSRF clasic, dar orice site poate apela liber
toate endpoint-urile publice de mai sus.

### P1.5 — Login fără rate limiting

> ⚠️ **PARȚIAL** la 2026-07-10. Comparația parolei folosește acum `hmac.compare_digest` (timp constant)
> în `login()`, `bot_stop()` și `bot_start()`. **Rate limiting-ul lipsește în continuare** —
> `POST /api/auth/login` acceptă tot un număr nelimitat de încercări. Problema rămâne **DESCHISĂ**
> pentru această parte.

[`app.py:156`](../backend/app.py)

`POST /api/auth/login` acceptă încercări nelimitate. Parola vine din mediu, în clar, și e comparată
cu `==`.

### P1.6 — Încărcare de fișiere fără limite

[`app.py:998`](../backend/app.py)

`allowed_file()` verifică **doar extensia**. Nu există `MAX_CONTENT_LENGTH`, nu se verifică tipul
real al conținutului, nu se recodează imaginea. Un `.png` de 2 GB umple discul; un `.png` care e de
fapt HTML e servit de `/api/static/uploads/<filename>`.

`send_from_directory` blochează traversarea de căi, deci acolo e în regulă.

---

## P2 — Corectitudine

### P2.1 — Reminderele se repetă la fiecare 5 minute

[`bot.py:500`](../backend/bot.py)

```python
job_queue.run_repeating(reminder_job, interval=300, first=10)
```

Nu există deduplicare. Un angajat care nu alege primește un reminder **la fiecare 5 minute** pe toată
fereastra 09:00–10:30 — **19 mesaje**.

Enum-ul `NotificationType.reminder` există în [`models.py:17`](../backend/models.py) dar nu e scris
niciodată. Infrastructura de deduplicare e pe jumătate construită.

**Reparație:** scrie `NotificationLog(type=reminder)` la trimitere și filtrează după el; sau trimite
la 2–3 momente fixe în loc de la fiecare 5 minute.

### P2.2 — `GET /api/report` dă 500 dacă un meniu a fost șters

> ✅ **REPARAT** la 2026-07-12, confirmat experimental. `DELETE /api/menus/<id>` curăță acum selecțiile
> care îl referă prin **oricare** dintre cele trei chei străine (`menu_id`, `felul1_menu_id`,
> `felul2_menu_id`), plus cele care referă o opțiune a meniului. Nu mai rămân rânduri orfane, deci
> raportul nu mai are ce să dereferențieze. Probă: raport `200` → șterg un meniu cu comenzi → raport
> tot `200` (înainte: `500`).

```python
"menu_name": s.menu.name,                          # ← explodează dacă s.menu e None
"sort_order": s.menu.sort_order if s.menu else 0,  # ← linia următoare se apără
```

Autorul știa că `s.menu` poate fi `None`, dar a protejat doar două din patru accesări.

Se ajungea acolo prin ștergerea unui meniu, care lăsa selecții cu `menu_id` orfan. Raportul zilei
devenea imposibil de generat, exact în momentul în care era nevoie de el.

### P2.3 — `DELETE /api/users/<id>` dă 500 pentru orice user marcat vreodată absent

> ✅ **REPARAT** la 2026-07-12, confirmat experimental. `delete_user()` șterge acum și rândurile din
> `attendance`. Probă: user marcat absent → `DELETE` întoarce `200`, zero rânduri orfane (înainte: `500`).

[`app.py`](../backend/app.py) — curăța `selections` și `notification_logs`, dar **nu** `attendance`.

**Confirmat experimental.** SQLAlchemy încerca să pună `NULL` în `attendance.user_id`, care e
`nullable=False`:

```
sqlite3.IntegrityError: NOT NULL constraint failed: attendance.user_id
```

Un utilizator care n-a fost niciodată debifat în grila de prezență se ștergea normal — de aceea bug-ul
a trecut neobservat. Unul care a lipsit măcar o zi devenea **imposibil de șters**.

Simetric, [`app.py:270`](../backend/app.py) — `DELETE /api/menus/<id>` nu atinge `selections`.
Acolo nu apare eroare, fiindcă `selections.menu_id` e `nullable=True`: rândul rămâne cu `menu_id`
orfan și declanșează **P2.2** la următorul raport.

SQLite nu impune cheile străine fără `PRAGMA foreign_keys=ON`, care nu e setat nicăieri.

**Reparație:** șterge și `Attendance.query.filter_by(user_id=...)` în `delete_user`, și
`Selection.query.filter_by(menu_id=...)` în `delete_menu`. Pe termen lung: `ondelete="CASCADE"`
pe FK-uri + activarea pragma.

### P2.4 — `POST /api/users/register` dă 500 la fiecare `/start` nou

> ✅ **REPARAT** la 2026-07-10. O cerere care trimite doar `telegram_id` + `username` pentru un
> utilizator inexistent întoarce acum `200` fără să creeze nimic, în loc de `KeyError` → 500.

[`app.py:466`](../backend/app.py) · [`bot.py:408`](../backend/bot.py)

`update_username` e înregistrat pe `filters.ALL` în `group=-1`, deci rulează înaintea oricărui
handler, la **orice** mesaj — inclusiv la primul `/start` al unui utilizator necunoscut. Trimite doar
`telegram_id` și `username`.

Backend-ul, negăsind utilizatorul, încearcă să-l creeze:

```python
user = User(telegram_id=telegram_id, first_name=data["first_name"], ...)  # KeyError → 500
```

Excepția e înghițită de `except Exception: pass` din bot, deci nu se vede nimic — în afară de un
500 în logurile backend-ului la fiecare înregistrare nouă.

**Reparație:** în `register_user`, tratează cererea fără `first_name` ca actualizare pură; ignoră
utilizatorii inexistenți.

### P2.5 — Dashboard-ul cere selecțiile pentru ziua greșită înainte de ora 03:00

[`Dashboard.tsx:143`](../frontend/src/pages/Dashboard.tsx)

```ts
return target.toISOString().split('T')[0]
```

`target` păstrează ora curentă locală. `toISOString()` convertește în UTC. În Chișinău (UTC+3 vara),
la ora locală 01:00 rezultatul e **ziua precedentă**.

Efect: un administrator care deschide panoul devreme dimineața vede selecțiile de ieri.
Se propagă și la fusul orar al browserului, care nu e neapărat cel al Moldovei.

**Reparație:** formatează local — `` `${y}-${pad(m)}-${pad(d)}` `` — nu prin UTC.

### P2.6 — „Mâncarea a sosit" dez-aprobă meniurile, ireversibil și neidempotent

[`app.py:609`](../backend/app.py)

Butonul face două lucruri: trimite notificările **și** pune `is_approved=False` pe meniurile zilei.

Apăsat din greșeală dimineața: meniurile dispar din Mini App, iar `/api/notify/pending-users`
întoarce `[]` (nu mai există meniu aprobat), deci reminderele se opresc. Recuperarea e manuală.

Apăsat de două ori: toată lumea primește notificarea de două ori, iar `notification_logs` capătă
rânduri duplicate.

**Reparație:** verifică dacă notificarea a fost deja trimisă azi (există deja în `notification_logs`);
separă dez-aprobarea de notificare.

### P2.7 — Cursă la scrierea selecției

[`app.py:399`](../backend/app.py)

Upsert-ul este citire-apoi-scriere, fără lock. Două cereri simultane de la același utilizator trec
amândouă de `Selection.query.filter_by(...).first()`, ambele inserează, iar constrângerea
`uq_user_date` respinge a doua cu `IntegrityError` — netratată, deci 500.

Puțin probabil în practică (`sending` blochează dublu-click în Mini App), dar nu imposibil.

### P2.8 — Fusuri orare amestecate în aceeași coloană

[`models.py:94`](../backend/models.py) vs [`app.py:403`](../backend/app.py)

`Selection.selected_at` are `default=datetime.now(timezone.utc)`, dar `app.py` scrie explicit
`now_moldova()`. Coloana conține ambele, în funcție de calea de scriere.

`Selection.date` are `default=date.today()` — ziua **serverului**, nu a Moldovei. Nu se manifestă
azi, fiindcă `app.py` trimite mereu `date` explicit.

`NotificationLog.sent_at` și `User.registered_at` sunt în UTC, dar afișate de frontend ca ore locale.

**Reparație:** o singură convenție — stochează UTC peste tot (`DateTime(timezone=True)`), convertește
doar la afișare.

### P2.9 — Două funcții de seed care nu fac același lucru

> ✅ **REPARAT** la 2026-07-12. Duplicarea a fost eliminată: `scheduler.seed_weekly_menus()` deleagă
> acum către `app.seed_default_menus()` + `ensure_andys_menus()`. O singură implementare.
>
> **Capcana s-a materializat exact cum prezicea documentul.** La trecerea pe două restaurante, copia
> din `scheduler.py` a rămas în urmă: copia săptămâna precedentă **fără** `restaurant` și **fără**
> opțiunile de Felul 1. În fiecare luni la 02:00, business lunch-urile Andy's s-ar fi transformat
> tăcut în meniuri Șezătoare goale — iar tabul Andy's ar fi rămas fără opțiuni.

[`app.py`](../backend/app.py) `seed_default_menus` copia **și conținutul** săptămânii trecute.
[`scheduler.py`](../backend/scheduler.py) `seed_weekly_menus` copia **doar structura**.

Rezultatul final părea același, fiindcă `reset_menu_content` golește conținutul luni la 02:01. Dar
oricine modifica una fără cealaltă introducea o divergență invizibilă.

Comentariul lui `cleanup_previous_week` ([`scheduler.py:18`](../backend/scheduler.py)) spune
„this week's selections". Șterge săptămâna **precedentă**. Codul e corect, comentariul nu.

### P2.10 — Fără validare la scrierea meniurilor

[`app.py:211`](../backend/app.py)

`POST /api/menus` acceptă orice `day_of_week` (inclusiv `7`, `-1`), nu limitează lungimea textelor,
și nu împiedică duplicatele — nu există constrângere de unicitate pe `(name, day_of_week, week_start_date)`.

---

## P3 — Operațional și întreținere

### P3.1 — Frontend-ul rulează serverul de dezvoltare Vite în producție

[`frontend/Dockerfile`](../frontend/Dockerfile) — `CMD ["npm", "run", "dev"]`

Fără minificare, fără cache, cu HMR și source maps expuse, cu un server care nu e proiectat pentru
trafic real. `npm run build` există în `package.json` și nu e folosit.

**Reparație:** build multi-stage → servește `dist/` cu nginx.

### P3.2 — `gunicorn` e instalat dar nu e folosit

[`requirements.txt:11`](../backend/requirements.txt) · [`backend/Dockerfile`](../backend/Dockerfile)
— `CMD ["python", "run.py"]`, adică serverul de dezvoltare Flask.

Trecerea la gunicorn nu e directă: `app.py` rulează `db.create_all()` + migrații **la nivel de modul**,
deci fiecare worker le-ar executa în paralel, în cursă. Iar `SECRET_KEY` random (P0.1) ar diferi
între workeri.

### P3.3 — `debug=True` în `app.py`

[`app.py:1259`](../backend/app.py). Nu se activează prin `run.py` (care are `debug=False`), dar
`python app.py` pornește Werkzeug cu consola de debug — execuție de cod la distanță.

### P3.4 — `PUT /api/bot/settings` la fiecare apăsare de tastă

[`Dashboard.tsx:373`](../frontend/src/pages/Dashboard.tsx)

`onChange` pe `<input type="time">` salvează imediat. Fiecare modificare a orei trimite un `PUT`.

### P3.5 — Salvarea meniurilor nu e atomică

[`MenuManagement.tsx:82`](../frontend/src/pages/MenuManagement.tsx) — `Promise.all` peste `PUT`-uri
independente. Dacă unul eșuează, restul rămân salvate și utilizatorul vede „Eroare la salvare".

### P3.6 — `BotControl.query.get()` este API depreciat

Folosit în 6 locuri din `app.py`. `Query.get()` e depreciat în SQLAlchemy 2.x → `db.session.get(BotControl, 1)`.

### P3.7 — Fără healthcheck, fără backup automat

`docker-compose.yml` nu definește `healthcheck` pentru niciun serviciu, deci `depends_on` pornește
botul înainte ca backend-ul să fie gata. Botul compensează cu retry exponențial în `api_get`/`api_post`.

Baza SQLite nu are niciun job de backup. Vezi [08-operare.md](08-operare.md#backup).

### P3.8 — Acoperire de teste aproape inexistentă

12 teste, toate pe `calculations.py`. Zero teste pentru: cele 43 de endpoint-uri, logica de
aprobare, filtrarea reminderelor, joburile de scheduler, Mini App.

`pytest` nu e în `requirements.txt`, deși README-ul îl recomandă. Testele sunt `unittest`.

### P3.9 — Configurație hardcodată

- `vite.config.ts:12` — `allowedHosts: ['cgam.md', 'iapbe.md']`
- `bot.py` — ora „9:00 — 10:30" scrisă în textul ghidului, deși fereastra e configurabilă din Dashboard
- `bot.py`, `app.py` — `@CroweTM_Office` scris în patru mesaje diferite

### P3.10 — README stale

[`README.md`](../README.md) afirmă:
- remindere „09:30–13:00" → în realitate `09:00`–`10:30`, configurabile
- „Înregistrare multilingvă (RO/RU/EN)" → engleza nu există în cod
- `python -m pytest test_calculations.py` → pytest nu e instalat
- structura de proiect omite `UserManagement`, `Instructions`, Mini App-ul

---

## Recomandarea de ordine

Toate P0-urile, plus P1.1, P1.2, P2.4 și parțial P1.3/P1.5, au fost închise la 2026-07-10. Rămân, în
ordinea recomandată:

1. **P1.5** (partea de rate limiting), **P3.3** — completează hardening-ul de securitate.
2. **P1.4** (CORS deschis) — restrânge originile permise.
3. **P2.2** + **P2.3** — raportul care crapă e o defecțiune vizibilă zilnic.
4. **P2.1** — 19 remindere e un motiv real ca oamenii să blocheze botul.
5. **P2.5**, **P2.6** — corectitudine (timezone dashboard, food-arrived idempotent).
6. **P1.6** — limite la upload de fișiere.
7. **P3.1**, **P3.2** — deploy serios.
8. Restul **P3.x** — operațional și întreținere.

Pentru hardening ai deja skill-ul `/app-security-harden`. Pentru verificarea că nimic nu s-a rupt
după reparații: `/meniubot-verify`.
