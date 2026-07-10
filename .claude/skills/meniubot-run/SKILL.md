---
name: meniubot-run
description: Pornește aplicația MeniuBot pe mașina locală (backend Flask, bot Telegram, panou admin) și confirmă printr-o sondă de sănătate că răspunde. Folosește-l când utilizatorul spune „pornește aplicația", „rulează local", „vreau să văd cum arată", „start docker", „ridică proiectul", „dă drumul la backend" sau „deschide panoul admin".
---

# MeniuBot - pornire locală

Acest skill ridică MeniuBot pe mașina locală și verifică activ că backend-ul răspunde. Sunt două căi: cu Docker (toate cele trei servicii dintr-o comandă) sau fără Docker (fiecare serviciu într-un terminal separat). Alege una singură, nu le amesteca pe același token de bot.

## Când folosești skill-ul

Folosește-l când vrei să vezi aplicația funcționând local: să deschizi panoul de administrare, să testezi backend-ul, sau să pornești botul de Telegram. Pentru testarea end-to-end a fluxului zilnic (login → aprobare meniu → selecție → alerte → raport → închidere) folosește în schimb `/meniubot-verify`. Pentru configurarea de producție cu nginx citește `docs/08-operare.md` — nu duplica acel config aici.

## Ce îți trebuie înainte

Un fișier `.env` în rădăcina proiectului (`/Users/ivanturcan/Desktop/Project/Meniubot`) cu, cel puțin:

```
TELEGRAM_BOT_TOKEN=...
SECRET_KEY=...
ADMIN_USERNAME=admin
ADMIN_PASSWORD=admin
OFFICE_ADDRESS=str. Exemplu 123, Chișinău
WEBAPP_URL=
FLASK_PORT=5000
DATABASE_URL=sqlite:///meniubot.db
API_BASE_URL=http://localhost:5000
```

Dacă lipsește `TELEGRAM_BOT_TOKEN`, botul scrie `TELEGRAM_BOT_TOKEN not set!` și iese imediat. Backend-ul și panoul admin pornesc și fără el; doar trimiterea de mesaje Telegram va fi dezactivată (`send_telegram_message()` întoarce `False` și doar loghează). Deci, dacă vrei doar backend + admin, fără mesaje reale, lasă tokenul nesetat.

La primul import, `app.py` rulează `db.create_all()` + `migrate_db()` + `seed_default_menus()`, așa că o bază goală capătă automat 20 de meniuri (4 șabloane × 5 zile). Nu trebuie să inițializezi nimic manual.

## Varianta Docker

`docker-compose.yml` are trei servicii: `backend` (rulează `python run.py`, expune 5000), `bot` (rulează `python bot.py`) și `frontend` (rulează `npm run dev`, expune 5173). Compose-ul cere o rețea externă numită `shared-network`, pe care trebuie s-o creezi înainte, altfel `up` eșuează.

```bash
cd /Users/ivanturcan/Desktop/Project/Meniubot
docker network create shared-network   # o singură dată; a doua oară dă eroare „already exists", e normal
docker compose up --build
```

Atenție: serviciile folosesc `expose`, nu `ports`. Nimic nu e publicat pe host, deci `http://localhost:5000` și `http://localhost:5173` NU sunt accesibile din browserul gazdei prin compose-ul standard. Verificarea de sănătate din compose se face din interiorul rețelei sau lovind containerul direct. Dacă vrei să accesezi panoul din browserul gazdei, folosește varianta fără Docker de mai jos (Vite ascultă pe `0.0.0.0:5173` și, rulat local, e publicat pe host), sau pune un nginx în față conform `docs/08-operare.md`.

Oprire:

```bash
cd /Users/ivanturcan/Desktop/Project/Meniubot
docker compose down
```

## Varianta fără Docker

Trei procese, fiecare în terminalul lui. Aceasta e calea recomandată dacă vrei să deschizi panoul admin în browser, pentru că porturile 5000 și 5173 rămân pe host.

Terminal 1 — backend:

```bash
cd /Users/ivanturcan/Desktop/Project/Meniubot/backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

`requirements.txt` conține: flask, flask-sqlalchemy, flask-cors, python-dotenv, PyJWT, python-telegram-bot[job-queue], httpx, APScheduler, pytz, requests, gunicorn.

Terminal 2 — botul de Telegram (doar dacă ai un token real și nu rulează deja un `docker compose up`):

```bash
cd /Users/ivanturcan/Desktop/Project/Meniubot/backend
source venv/bin/activate
python bot.py
```

Terminal 3 — panoul admin:

```bash
cd /Users/ivanturcan/Desktop/Project/Meniubot/frontend
npm install
npm run dev
```

Panoul se deschide la **http://localhost:5173/meniubot_admin/** — NU la `http://localhost:5173` (rădăcina dă 404, pentru că `base` din Vite e `/meniubot_admin/`). Login implicit: `admin` / `admin`.

Clientul axios are `baseURL` `/meniubot/api`, iar proxy-ul din `vite.config.ts` rescrie `/meniubot/api` → `/api` către backend-ul de pe `http://localhost:5000`. Astfel panoul merge în dev fără nginx, cu condiția ca backend-ul să fie pornit.

## Cum verifici că merge

Backend-ul expune endpointul public `GET /api/bot/status`, care întoarce JSON. Folosește-l ca sondă de sănătate cu o buclă de retry — nu un `sleep` orb — pentru că importul inițial (create_all + migrate + seed) durează câteva secunde:

```bash
for i in $(seq 1 30); do
  if curl -sf http://localhost:5000/api/bot/status > /dev/null; then
    echo "backend UP"
    curl -s http://localhost:5000/api/bot/status
    break
  fi
  echo "aștept backend-ul... ($i/30)"
  sleep 1
done
```

Dacă bucla trece de 30 de încercări fără succes, backend-ul nu a pornit — verifică logurile procesului din Terminal 1 (sau `docker compose logs backend`).

Pentru panoul admin, după ce backend-ul e UP, deschide http://localhost:5173/meniubot_admin/ și autentifică-te cu `admin`/`admin`. Dacă pagina se încarcă dar cererile API dau eroare, backend-ul nu răspunde pe 5000 sau proxy-ul Vite nu a pornit.

## Ce NU merge local

**Mini App-ul de Telegram.** Flask îl servește la `/webapp`, dar pagina face fetch pe `/meniubot/api`, iar Flask NU are rute sub `/meniubot` (rutele lui sunt sub `/api`). Deci, local și fără nginx, pagina Mini App se încarcă, dar toate fetch-urile dau 404. Rescrierea `/meniubot/api` → `/api` există doar în proxy-ul Vite (care servește panoul admin, nu Mini App-ul). Ca să testezi Mini App-ul complet îți trebuie un nginx în față care să facă acea rescriere — vezi `docs/08-operare.md`.

## Capcane

- **`shared-network` lipsă.** `docker compose up` eșuează dacă rețeaua externă nu există. Rulează `docker network create shared-network` o singură dată, înainte.
- **Două instanțe de bot pe același token.** `bot.py` are `check_no_other_instance()` și refuză pornirea dacă e setat un webhook pe token. Mai grav: două instanțe active (de ex. `docker compose up` care rulează serviciul `bot` ȘI un `python bot.py` pornit manual) își împart update-urile aleatoriu, deci selecțiile utilizatorilor se pierd. Rulează botul într-un singur loc.
- **Portul 5173 fără cale.** `http://localhost:5173` dă 404. Calea corectă e `http://localhost:5173/meniubot_admin/`, din cauza lui `base: '/meniubot_admin/'`.
- **`allowedHosts` hardcodat.** `vite.config.ts` are `allowedHosts: ['cgam.md', 'iapbe.md']`. `localhost` și `127.0.0.1` sunt permise implicit de Vite, deci accesul local merge; dar dacă pui în față alt hostname, trebuie adăugat aici, altfel Vite blochează cererea.
- **`expose` vs `ports` în Docker.** Compose-ul nu publică nimic pe host. Pentru acces din browserul gazdei, folosește varianta fără Docker sau un reverse proxy.

## Vezi și

- `/meniubot-verify` — testarea end-to-end a fluxului zilnic pe o bază de date temporară.
- `docs/08-operare.md` — deploy de producție și configurația nginx (inclusiv rescrierea necesară Mini App-ului).
- `docs/09-probleme-cunoscute.md` — probleme cunoscute.
