# 08 — Operare și deploy

## Variabile de mediu

Un singur `.env` la rădăcină, citit de `docker-compose.yml`. (Există și `backend/.env.example`,
pentru rularea fără Docker.)

| Variabilă | Folosită de | Obligatorie | Implicit |
|-----------|-------------|:-----------:|----------|
| `TELEGRAM_BOT_TOKEN` | backend, bot | **da** | — |
| `SECRET_KEY` | backend | **da** | — (fără default; aplicația nu pornește fără el) |
| `INTERNAL_API_TOKEN` | backend, bot | **da** | — (fără default; ambele procese refuză să pornească fără el) |
| `ADMIN_USERNAME` | backend | da | `admin` |
| `ADMIN_PASSWORD` | backend | da | `admin` |
| `WEBAPP_URL` | bot | **da** pentru Mini App | gol → butonul nu apare |
| `OFFICE_ADDRESS` | backend, bot | nu | `str. Exemplu 123, Chișinău` |
| `DATABASE_URL` | backend | nu | `sqlite:///meniubot.db` |
| `FLASK_PORT` | backend | nu | `5000` |
| `API_BASE_URL` | bot | nu | `http://backend:5000` |

> **`SECRET_KEY` este acum obligatorie.** Nu mai există niciun default: `app.py` ridică `RuntimeError`
> la pornire dacă lipsește, e gol, sau e una din valorile respinse explicit (`dev-secret-key`,
> `your_secret_key`). În `docker-compose.yml` se folosește sintaxa `${SECRET_KEY:?...}`, deci `docker
> compose up` eșuează cu mesaj clar dacă `.env` n-o definește. Același regim pentru `INTERNAL_API_TOKEN`
> (secretul partajat între backend și bot, trimis în headerul `X-Internal-Token`).
> Generează fiecare valoare: `python3 -c "import secrets; print(secrets.token_hex(32))"`

`WEBAPP_URL` trebuie să fie **HTTPS**. Telegram refuză WebApp-urile pe HTTP.

## Docker

```bash
cp .env.example .env    # completează TELEGRAM_BOT_TOKEN, SECRET_KEY, INTERNAL_API_TOKEN, ADMIN_PASSWORD, WEBAPP_URL
docker compose up --build
```

Trei servicii:

| Serviciu | Comandă | Port | Volume |
|----------|---------|------|--------|
| `backend` | `python run.py` | `5000` (expose) | `backend_data:/app/instance`, `uploads_data:/app/static/uploads` |
| `bot` | `python bot.py` | — | — |
| `frontend` | `npm run dev` | `5173` (expose) | — |

`backend` și `frontend` sunt atașate la rețeaua externă `shared-network` — trebuie să existe
înainte de `up`:

```bash
docker network create shared-network
```

`expose` (nu `ports`) înseamnă că nimic nu e publicat pe host. Accesul trece obligatoriu prin
reverse proxy.

> `frontend` rulează serverul de **dezvoltare** Vite, nu un build static.
> Vezi [09-probleme-cunoscute.md](09-probleme-cunoscute.md#p6--frontend-ul-rulează-serverul-de-dezvoltare-vite-în-producție).

`vite.config.ts` are `allowedHosts: ['cgam.md', 'iapbe.md']` — hardcodat. Un domeniu nou trebuie
adăugat acolo, altfel Vite respinge cererea.

## Reverse proxy (obligatoriu)

Flask servește rutele sub `/api`. Ambii clienți cheamă `/meniubot/api`. Rescrierea trebuie făcută
de proxy. Fără ea, **Mini App-ul nu funcționează deloc** — panoul de admin merge doar în dev, prin
proxy-ul Vite.

```nginx
server {
    server_name cgam.md;
    listen 443 ssl;

    # API — rescrie /meniubot/api/* → /api/*
    location /meniubot/api/ {
        proxy_pass http://backend:5000/api/;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        client_max_body_size 10M;   # imaginile din Instrucțiuni
    }

    # Telegram Mini App
    location /webapp {
        proxy_pass http://backend:5000/webapp;
        proxy_set_header Host $host;
    }

    # Panoul de administrare
    location /meniubot_admin/ {
        proxy_pass http://frontend:5173/meniubot_admin/;
        proxy_set_header Host    $host;
        proxy_set_header Upgrade $http_upgrade;   # HMR Vite
        proxy_set_header Connection "upgrade";
    }
}
```

Apoi în `.env`: `WEBAPP_URL=https://cgam.md/webapp`

Cele trei prefixe sunt fixate în cod:
- `/meniubot/api` — [`frontend/src/api/client.ts`](../frontend/src/api/client.ts) și `API_BASE` din Mini App
- `/meniubot_admin` — `basename` în [`App.tsx`](../frontend/src/App.tsx) și `base` în `vite.config.ts`
- `/webapp` — ruta Flask și `WEBAPP_URL`

## Fără Docker

```bash
# backend
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

python run.py     # terminal 1 — API + scheduler, :5000
python bot.py     # terminal 2 — botul Telegram
```

```bash
# frontend
cd frontend
npm install
npm run dev       # :5173, cu proxy către :5000
```

Panoul: `http://localhost:5173/meniubot_admin/`

Mini App-ul **nu** va funcționa local fără nginx — `http://localhost:5000/webapp` se încarcă, dar
toate fetch-urile către `/meniubot/api` dau 404.

## Teste

```bash
cd backend
python -m unittest test_calculations -v      # 12 teste, toate trec
python -m unittest test_auth -v              # 15 teste — validarea initData Telegram
```

Total: **27** de teste. `python -m unittest test_calculations test_auth -v` le rulează pe toate deodată.

> README-ul spune `python -m pytest`, dar **pytest nu e în `requirements.txt`**. Testele sunt scrise
> cu `unittest`, deci comanda de mai sus e cea corectă. `pytest test_calculations.py` funcționează
> totuși, dacă pytest e instalat separat.

Acoperirea: `calculations.py` (calculul porțiilor și formatul raportului) și `auth.py` (validarea
`initData` de la Telegram). Nu există încă teste pentru celelalte endpoint-uri, pentru bot sau
pentru scheduler.

## Un singur proces bot per token

Telegram împarte update-urile aleatoriu între instanțele care fac polling pe același token.
Două instanțe = selecții pierdute și remindere duplicate.

`check_no_other_instance()` verifică la pornire dacă e setat un webhook și refuză să pornească.
Nu poate detecta un al doilea poller. Dacă rulezi `docker compose up` în timp ce ai `python bot.py`
într-un terminal, ai două.

La pornire, botul face `drop_pending_updates=True` — mesajele primite cât timp era oprit se pierd.

## Backup

Baza de date este un singur fișier SQLite, în volumul `backend_data`:

```bash
docker compose exec backend sqlite3 /app/instance/meniubot.db ".backup '/tmp/backup.db'"
docker compose cp backend:/tmp/backup.db ./backup-$(date +%F).db
```

Imaginile din Instrucțiuni sunt în volumul `uploads_data` și **nu** sunt în bază — un backup fără
ele lasă instrucțiunile cu imagini rupte.

Nu există niciun job de backup automat.

## Migrații

Nu există Alembic. La fiecare import al modulului `app`, `migrate_db()` și `migrate_bot_control()`
inspectează schema și adaugă coloanele lipsă cu `ALTER TABLE`.

Consecințe:
- adaugi o coloană nouă → o adaugi **și** în model, **și** în dicționarul din `migrate_*()`
- nu există rollback și nici versionare
- câteva instrucțiuni sunt SQL specific SQLite (`date('now', 'weekday 1', '-7 days')`) — migrarea
  la Postgres cere rescrierea lor

Skill-ul `/meniubot-api-endpoint` acoperă tiparul corect.
