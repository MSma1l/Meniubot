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

```bash
docker compose up --build
```

### 3. Acces

- **Admin Panel**: http://localhost:5173
  - Login: `admin` / `admin`
- **Telegram Bot**: deschideți botul în Telegram și trimiteți `/start`

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
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/          # Login, Dashboard, MenuManagement
│   │   ├── components/     # NavBar
│   │   └── api/            # Axios client
│   └── ...
├── docker-compose.yml
└── .env.example
```

## Funcționalități

### Telegram Bot
- Înregistrare multilingvă (RO/RU/EN)
- Vizualizare și selectare meniu zilnic
- Notificări reminder (09:30–13:00, la fiecare 5 minute)
- Notificare "Mâncarea a sosit"

### Admin Panel
- Dashboard zilnic cu selecțiile angajaților (auto-refresh 30s)
- Gestionare meniu săptămânal (Luni–Vineri)
- Aprobare meniu pe zi
- Export raport cu calcul automat de porții
- Notificare "Mâncarea a sosit" cu un click

### Logica de calcul porții
- **Ambele** (Felul 1 + Felul 2) → 1 porție Maxi
- **Felul 2** singur → 1 porție Standard
- **Felul 1** singur × 2 → se combină în 1 porție Maxi
- **Felul 1** singur × 1 (fără pereche) → 1 porție Standard

## Teste

```bash
cd backend
python -m pytest test_calculations.py -v
```
