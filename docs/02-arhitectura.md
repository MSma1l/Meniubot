# 02 — Arhitectură

## Patru componente, trei procese

```
                        ┌──────────────────────────────┐
   Angajat ──Telegram──▶│  bot.py  (proces separat)    │
                        │  polling, remindere, /start  │
                        └──────────────┬───────────────┘
                                       │ HTTP (httpx)
                                       ▼
   Angajat ──Mini App───────▶┌──────────────────────────┐
   (WebView în Telegram)     │  app.py  (Flask + API)   │
                             │  + scheduler.py (cron)   │
   Admin ──React SPA────────▶│  + SQLite                │
                             └──────────────────────────┘
                                       ▲
                                       │ Telegram Bot API (requests)
                                       └──▶ mesaje către angajați
```

Trei containere în `docker-compose.yml`: `backend`, `bot`, `frontend`.

### 1. `backend` — Flask API + scheduler

Punct de intrare [`run.py`](../backend/run.py): pornește APScheduler, apoi serverul Flask pe `:5000`.

- [`app.py`](../backend/app.py) — 43 de endpoint-uri, plus migrațiile și seed-ul la import
- [`models.py`](../backend/models.py) — 7 modele SQLAlchemy
- [`calculations.py`](../backend/calculations.py) — calculul porțiilor și textul raportului (pur, fără I/O)
- [`scheduler.py`](../backend/scheduler.py) — 5 joburi cron

Backend-ul **trimite el însuși** mesajele Telegram, prin `requests` direct la Bot API
(`send_telegram_message()`), nu prin procesul bot. Notificarea „mâncarea a sosit", confirmarea
selecției și mesajul de închidere a comenzilor pleacă toate de aici.

### 2. `bot` — procesul Telegram

[`bot.py`](../backend/bot.py), `python-telegram-bot` v21, long polling. Rulează din aceeași imagine
Docker ca backend-ul, dar cu `command: python bot.py`.

Responsabilități: conversația de înregistrare (`/start` → limbă → nume), comenzile `/menu` și `/guide`,
butonul de meniu al chat-ului, și **jobul de remindere** (la fiecare 5 minute).

Botul **nu atinge baza de date direct**. Vorbește doar prin HTTP cu backend-ul, cu retry exponențial
la pornire (`api_get` / `api_post`, 3 încercări: 1s, 2s, 4s) fiindcă `depends_on` nu așteaptă ca
backend-ul să fie gata.

`check_no_other_instance()` verifică la pornire că nu există webhook setat pe același token — două
instanțe care fac polling pe același token își împart update-urile aleatoriu, ceea ce înseamnă
selecții pierdute și remindere duplicate.

### 3. `frontend` — panoul de administrare

React 19 + Vite + react-router. Cinci pagini: Login, Dashboard, MenuManagement, UserManagement,
Instructions. Autentificare cu JWT păstrat în `localStorage`.

Servit sub `basename="/meniubot_admin"`. Clientul axios ([`api/client.ts`](../frontend/src/api/client.ts))
are `baseURL: '/meniubot/api'` și atașează `Authorization: Bearer <token>` la fiecare cerere.
La orice `401`, șterge token-ul și redirecționează la `/login`.

> Containerul `frontend` rulează `npm run dev` — **serverul de dezvoltare Vite**, inclusiv în producție.
> Vezi [09-probleme-cunoscute.md](09-probleme-cunoscute.md).

### 4. Mini App — Telegram WebApp

Un singur fișier: [`backend/static/webapp/index.html`](../backend/static/webapp/index.html),
764 de linii de HTML + CSS + JS vanilla, fără build step. Servit de Flask la ruta `/webapp`.

Citește identitatea utilizatorului din `window.Telegram.WebApp.initDataUnsafe.user.id`, se adaptează
la tema Telegram (light/dark), și face fetch pe aceeași bază `/meniubot/api` ca panoul de admin.

## Rutarea — partea cea mai fragilă

Flask înregistrează rutele sub prefixul `/api`. Dar **ambii** clienți (panoul de admin și Mini App-ul)
cheamă `/meniubot/api`. Diferența e acoperită în două locuri diferite:

**În dezvoltare**, de proxy-ul Vite ([`vite.config.ts`](../frontend/vite.config.ts)):

```ts
proxy: { '/meniubot/api': { target: API_URL, rewrite: p => p.replace(/^\/meniubot\/api/, '/api') } }
```

Asta acoperă doar panoul de admin, fiindcă el e servit de Vite.

**În producție**, de un reverse proxy (nginx) care trebuie să facă aceeași rescriere — și care e
**singurul** lucru care face Mini App-ul să funcționeze. Mini App-ul e servit de Flask la `/webapp`,
dar cheamă `/meniubot/api/...` pe același origin. Flask nu are nicio rută sub `/meniubot`. Fără nginx,
fiecare fetch din Mini App primește 404.

Configurația nginx cerută: [08-operare.md](08-operare.md#reverse-proxy-obligatoriu).

## Fluxul unei selecții, cap-coadă

1. Angajatul apasă butonul din reminder → Telegram deschide `WEBAPP_URL` într-un WebView.
2. Mini App-ul cheamă `GET /api/users/check/<telegram_id>` → află limba și numele.
3. `GET /api/webapp/ordering-status` → dacă e închis, afișează ecranul „comenzi închise" și se oprește.
4. `GET /api/webapp/my-selection?telegram_id=…` → dacă a ales deja, afișează alegerea + butonul „schimb".
5. `GET /api/menus/today/approved` → randează câte o secțiune per meniu.
6. Angajatul alege, apasă „Confirmă" → `POST /api/selections` cu `{telegram_id, menu_id, fel_selectat, source:"webapp"}`.
7. Backend-ul verifică dacă preluarea comenzilor e deschisă, face upsert pe `(user_id, date)`,
   apoi — pentru că `source == "webapp"` — trimite confirmarea pe Telegram cu conținutul meniului ales.
8. Mini App-ul afișează ecranul de succes și se închide după 2,5 secunde.

## Fusul orar

Tot ce ține de logica de business folosește `ZoneInfo("Europe/Chisinau")`, prin helper-ele
`today_moldova()` / `now_moldova()` (în `app.py`) și `today_md()` / `now_md()` (în `scheduler.py`, `bot.py`).
APScheduler e configurat cu `timezone="Europe/Chisinau"`.

Excepție: valorile `default` din modele (`Selection.selected_at`, `NotificationLog.sent_at`,
`User.registered_at`) sunt în **UTC**. În practică `app.py` suprascrie `selected_at` cu ora Moldovei,
deci coloana conține un amestec. Vezi [09-probleme-cunoscute.md](09-probleme-cunoscute.md).

## Persistență

SQLite, un fișier, montat pe volumul Docker `backend_data:/app/instance`. Imaginile încărcate pentru
instrucțiuni stau pe `uploads_data:/app/static/uploads`.

Nu există Alembic. Migrațiile sunt scrise de mână în `migrate_db()` și `migrate_bot_control()`, care
rulează la fiecare import al modulului `app` și adaugă coloanele lipsă cu `ALTER TABLE`. Câteva
instrucțiuni sunt SQL specific SQLite (`date('now', 'weekday 1', '-7 days')`), deci trecerea la
Postgres nu e directă.
