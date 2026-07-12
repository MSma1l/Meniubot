---
name: meniubot-preflight
description: Checklist automat înainte de deploy MeniuBot — verifică secretele implicite, endpoint-urile publice, debug-ul Flask și configul hardcodat, apoi spune exact ce trebuie reparat. Declanșatoare: „gata de deploy?", „preflight", „e sigur să pun în producție", „verifică configurația".
---

# MeniuBot Preflight

Acest skill rulează un singur script Python care trece prin toate capcanele
cunoscute de configurare și securitate ale MeniuBot înainte de a pune aplicația
în producție. Nu instalează nimic și nu are dependențe externe: folosește doar
biblioteca standard Python 3.

## Când îl folosești

Îl folosești chiar înainte de un deploy sau ori de câte ori cineva întreabă
„e sigur să pun în producție?", „preflight", „gata de deploy?" sau „verifică
configurația". Îl rulezi și după orice modificare în `backend/app.py`,
`docker-compose.yml`, `.env` sau în fișierele frontend, pentru că verifică exact
zonele care se strică cel mai des.

## Cum se rulează

```bash
python3 .claude/skills/meniubot-preflight/scripts/preflight.py [--root .] [--env .env]
```

- `--root` — rădăcina repo-ului MeniuBot (implicit directorul curent).
- `--env` — calea către fișierul `.env` (implicit `<root>/.env`). Folosește-o
  când vrei să validezi un `.env` aflat în altă parte, fără să-l pui în repo.

Codul de ieșire este **0** dacă nu există niciun eșec BLOCANT și **1** dacă
există cel puțin unul. Avertismentele **nu** schimbă codul de ieșire și **nu**
blochează deploy-ul — sunt doar lucruri de care trebuie să fii conștient.

## Blocant vs. avertisment

Un eșec **BLOCANT** (`✗`, roșu) înseamnă că deploy-ul nu e sigur: un secret
implicit, un endpoint public neașteptat, debug-ul pornit sau `.env` care ar
ajunge în git. Trebuie reparat înainte de deploy.

Un **avertisment** (`!`, galben) înseamnă o problemă cunoscută sau o
neconcordanță de configurare care merită atenție, dar pe care echipa a decis
deja s-o tolereze deocamdată. Nu blochează deploy-ul.

Un `✓` verde înseamnă că verificarea a trecut. La final scriptul afișează un
sumar de forma `N blocante, M avertismente`.

## Ce verifică, punct cu punct

**Blocante:**

1. **`.env` există** la rădăcină. Dacă lipsește → rulează `cp .env.example .env`
   și completează valorile reale.
2. **`SECRET_KEY`** e setat, nu e gol, nu e `your_secret_key` sau
   `dev-secret-key`, și are cel puțin 32 de caractere. `app.py` respinge explicit
   `dev-secret-key` și `your_secret_key` și **nu pornește deloc** fără un
   `SECRET_KEY` valid (ridică `RuntimeError`). Generează unul real cu
   `python3 -c "import secrets; print(secrets.token_hex(32))"`.
2b. **`INTERNAL_API_TOKEN`** e setat, nevid, are cel puțin 32 de caractere și e
   diferit de valoarea de test `test-internal-token`. E secretul cu care procesul
   bot se autentifică la API-ul intern (`/users/register`,
   `/notify/pending-users`). `app.py` ridică `RuntimeError` și **nu pornește**
   fără el. Generează-l cu
   `python3 -c "import secrets; print(secrets.token_hex(32))"`.
3. **`ADMIN_PASSWORD`** e setat și nu e `admin`.
4. **`TELEGRAM_BOT_TOKEN`** e setat și nu e `your_token_here`.
5. **`WEBAPP_URL`** e setat, începe cu `https://` (Telegram refuză WebApp pe
   http) și nu conține `yourdomain.com`.
6. **`backend/app.py` nu conține `debug=True`** (apare la finalul fișierului, în
   blocul `if __name__ == "__main__"`). Debug-ul Werkzeug expune un debugger cu
   execuție de cod la distanță.
7. **Nicio rută publică nouă.** Scriptul parsează `backend/app.py` cu `ast`,
   enumeră toate funcțiile la nivel de modul decorate cu `@app.route` și le
   marchează publice pe cele care **nu au niciun** decorator de autentificare
   (`token_required`, `require_telegram`, `require_internal`,
   `require_telegram_or_internal`). Le compară cu lista de referință de **8 rute
   publice** acceptate azi: `login`, `get_approved_menus_today`, `bot_status`,
   `ordering_status`, `serve_webapp`, `webapp_ordering_status`, `serve_upload`,
   `get_instructions`. Dacă apare o rută publică nouă care nu e în listă →
   blocant: confirmă că e intenționată sau adaugă un decorator de autentificare.
12. **`.gitignore` conține `.env`.** Altfel secretele ar putea fi comise.

**Avertismente:**

7. (partea de reamintire) Când lista publică e neschimbată, scriptul îți
   amintește că **găurile P0 sunt închise** — selecțiile cer `initData` semnat,
   `register` / `pending-users` cer `X-Internal-Token`, iar `bot/stop` și
   `bot/start` cer JWT admin. Ce rămâne deschis: **nu există rate limiting pe
   `POST /api/auth/login`** (P1.5 — brute-force) și **CORS-ul e complet deschis**
   (`CORS(app)` fără origini restrânse, P1.4). Vezi
   `docs/09-probleme-cunoscute.md`.
8. **`frontend/Dockerfile` rulează `npm run dev`** — serverul de dezvoltare Vite
   în producție. Trebuie build multi-stage + nginx.
9. **`allowedHosts` din `frontend/vite.config.ts`** — dacă host-ul din
   `WEBAPP_URL` nu e în listă, Vite blochează cererile de pe acel domeniu.
10. **`gunicorn` e în `requirements.txt` dar `backend/Dockerfile` rulează
    `python run.py`** — gunicorn instalat, dar nefolosit. Nu trece la gunicorn
    înainte de a scoate `db.create_all()` și migrațiile de la nivel de modul din
    `app.py`, altfel rulează în fiecare worker.
11. **`docker-compose.yml` nu are `healthcheck`.**
13. **Teste** — comanda corectă este
    `cd backend && python -m unittest test_calculations test_auth -v`. README
    recomandă `pytest`, dar `pytest` nu e în `requirements.txt`; folosește
    `unittest` sau adaugă `pytest`. Scriptul îți amintește și că fluxul zilnic
    (cele două restaurante) nu e acoperit de unittest — pentru el rulează
    `/meniubot-verify` (`smoke.py --in-process`).

## Starea de referință a repo-ului curat

Pe repo-ul curat, fără `.env` (doar `.env.example`), scriptul dă:

**2 blocante, 4 avertismente** (cod de ieșire 1) — cifre măsurate, nu inventate.

- Blocante: `.env` lipsește și `backend/app.py` conține `debug=True`.
  (Verificările de secrete — inclusiv `[2b] INTERNAL_API_TOKEN` — sunt *sărite*
  când `.env` lipsește, deci nu adaugă blocante pe repo-ul curat.)
- Avertismente: reamintirea de la rute (P0 închise, rămân P1.5 rate limiting și
  P1.4 CORS), `npm run dev` în frontend, gunicorn nefolosit, lipsa unui
  healthcheck.

Verificarea `[13] Teste` trece, fiindcă README-ul folosește deja `unittest`. Ea
caută o **comandă** `pytest` reală, nu simpla apariție a cuvântului — README-ul
menționează `pytest` tocmai ca să spună că nu e instalat.

Parsarea `ast` a rutelor găsește exact **45 de rute** `@app.route`, dintre care
exact **8 publice** (`login`, `get_approved_menus_today`, `bot_status`,
`ordering_status`, `serve_webapp`, `webapp_ordering_status`, `serve_upload`,
`get_instructions`), toate în lista de referință acceptată.

> **45, nu 43.** Restructurarea pe două restaurante a adus trei rute noi de
> opțiuni Andy's — `POST /api/menus/<id>/options`, `PUT /api/menu-options/<id>`,
> `DELETE /api/menu-options/<id>` — și a șters `GET /api/selections/alerts`
> (Maxi/Standard nu mai există, deci nici alerta „Felul 1 nepereche"). Net: +2.
> Toate trei rutele noi au `@token_required`, deci **numărul de rute publice a
> rămas 8**. Numărul total nu e hardcodat nicăieri în script — `ast` îl numără la
> fiecare rulare; ce contează e ca lista publică să nu crească.

Când completezi un `.env` bun (cu `--env`), verificările 1–5 trec, host-ul din
`WEBAPP_URL` e comparat cu `allowedHosts`, iar singurul blocant rămas este
`debug=True`.

## Context și documentație

Pentru fundalul fiecărei probleme vezi `docs/09-probleme-cunoscute.md`:

- **P0.1** — `SECRET_KEY` cu default public — acum `app.py` refuză să pornească
  fără un secret valid (verificarea 2). **Închis.**
- **P0.2** — `initData` Telegram nevalidat în `create_selection` — acum
  `@require_telegram` verifică semnătura (verificarea 7). **Închis.**
- **P0.3** — `bot/stop` / `bot/start` publice — acum `@token_required`
  (verificarea 7). **Închis.**
- **P0.4** — `register_user` / `pending-users` fără autentificare — acum
  `@require_internal` (`X-Internal-Token`). **Închis.**
- **P1.4** — CORS complet deschis, `CORS(app)` fără origini restrânse
  (reamintire la verificarea 7). Rămâne deschis.
- **P1.5** — fără rate limiting pe `POST /api/auth/login`, vulnerabil la
  brute-force (reamintire la verificarea 7). Rămâne deschis.
- **P3.1** — Vite (serverul de dezvoltare) în producție (verificarea 8).
- **P3.2** — gunicorn instalat dar nefolosit (verificarea 10).

Pentru configurarea nginx și operarea în producție vezi `docs/08-operare.md`.
