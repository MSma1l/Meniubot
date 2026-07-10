# MeniuBot — Sistem de Gestionare a Mesei Corporative

Sistem complet pentru gestionarea comenzilor de prânz corporativ:
- **Telegram Bot** — angajații aleg meniul zilnic
- **Admin Panel** (React) — gestionare meniu, vizualizare comenzi, notificări
- **Flask API** — backend pentru toate componentele

## Arhitectură

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ Telegram Bot │────▶│  Flask API   │◀────│ React Admin  │
└─────────────┘     │  + SQLite    │     └──────────────┘
                    └──────────────┘
```

## Pornire rapidă cu Docker

### 1. Configurare

```bash
cp .env.example .env
```

Editați `.env` și adăugați `TELEGRAM_BOT_TOKEN` de la [@BotFather](https://t.me/BotFather).

### 2. Lansare

`docker-compose.yml` folosește rețeaua externă `shared-network`, deci creați-o o singură dată înainte de prima pornire:

```bash
docker network create shared-network
docker compose up --build
```

### 3. Acces

- **Admin Panel**: http://localhost:5173/meniubot_admin/ (panoul rulează sub basename `/meniubot_admin/`)
  - Login: `admin` / `admin`
- **Telegram Bot**: deschideți botul în Telegram și trimiteți `/start`

> ⚠️ **Mini App-ul NU funcționează fără reverse proxy** care mapează `/meniubot/api` → backend `/api`. Vezi [docs/08-operare.md](docs/08-operare.md).

## Pornire fără Docker

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# editați .env

# Terminal 1 — API server
python run.py

# Terminal 2 — Telegram bot
python bot.py
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

## Structura proiectului

```
├── backend/
│   ├── app.py              # Flask API + endpoints
│   ├── models.py           # SQLAlchemy models
│   ├── bot.py              # Telegram bot (async)
│   ├── scheduler.py        # APScheduler (cleanup săptămânal)
│   ├── calculations.py     # Logica de calcul porții
│   ├── test_calculations.py # Unit tests
│   ├── run.py              # Entry point (API + scheduler)
│   ├── static/webapp/index.html # Telegram Mini App (vanilla JS)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/          # Login, Dashboard, MenuManagement,
│   │   │                   #   UserManagement, Instructions
│   │   ├── components/     # NavBar
│   │   └── api/            # Axios client
│   └── ...
├── docs/                   # Documentație detaliată (01..09)
├── docker-compose.yml
└── .env.example
```

## Funcționalități

### Telegram Bot
- Înregistrare multilingvă (RO/RU)
- Vizualizare și selectare meniu zilnic
- Notificări reminder (fereastră implicită 09:00–10:30, configurabilă din Dashboard, la fiecare 5 minute)
- Notificare "Mâncarea a sosit"

### Admin Panel
- Dashboard zilnic cu selecțiile angajaților (auto-refresh 30s)
- Gestionare meniu săptămânal (Luni–Vineri)
- Aprobare meniu pe zi
- Export raport cu calcul automat de porții
- Notificare "Mâncarea a sosit" cu un click
- Gestionarea utilizatorilor (activare, editare, ștergere)
- Prezența angajaților pe zi
- Instrucțiuni pentru utilizatori (editabile de admin)
- Stopul de urgență al botului (pornit/oprit)
- Închiderea preluării comenzilor pe zi
- Modul sărbătoare (suspendă reminderele)

### Logica de calcul porții
- **Ambele** (Felul 1 + Felul 2) → 1 porție Maxi
- **Felul 2** singur → 1 porție Standard
- **Felul 1** singur × 2 → se combină în 1 porție Maxi
- **Felul 1** singur × 1 (fără pereche) → 1 porție Standard

## Teste

`pytest` nu este în `backend/requirements.txt`; testele rulează cu `unittest` (12 teste):

```bash
cd backend
python -m unittest test_calculations -v
```

## Documentație

Documentația completă e în [`docs/`](docs/README.md):

| # | Document | Ce găsești |
|---|----------|-----------|
| 01 | [Concept și idee](docs/01-concept.md) | Problema rezolvată, actorii, ziua tipică |
| 02 | [Arhitectură](docs/02-arhitectura.md) | Cele 4 componente, fluxul datelor, rutarea |
| 03 | [Model de date](docs/03-model-date.md) | Tabele, relații, invariante |
| 04 | [Referință API](docs/04-api.md) | Cele 43 de endpoint-uri, cu nivel de acces |
| 05 | [Funcționalități](docs/05-functionalitati.md) | Fiecare funcție, în detaliu |
| 06 | [Cicluri de timp](docs/06-cicluri-timp.md) | Ciclul zilnic, cel săptămânal, joburile cron |
| 07 | [Multilingv (RO/RU)](docs/07-i18n.md) | Unde trăiesc textele și cum le sincronizezi |
| 08 | [Operare și deploy](docs/08-operare.md) | Variabile de mediu, Docker, nginx, teste |
| 09 | [Probleme cunoscute](docs/09-probleme-cunoscute.md) | Audit securitate + corectitudine |

## Skill-uri

Skill-uri Claude Code din `.claude/skills/`, invocate cu `/`:

- `/meniubot-run` — pornește stack-ul local și îl verifică
- `/meniubot-verify` — testează end-to-end fluxul zilnic
- `/meniubot-i18n` — adaugi/schimbi texte RO/RU (4 fișiere)
- `/meniubot-api-endpoint` — adaugi un endpoint nou
- `/meniubot-preflight` — checklist înainte de deploy
