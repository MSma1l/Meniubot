# MeniuBot — ghid pentru Claude Code

Sistem de comandă a prânzului corporativ: angajații aleg meniul zilnic printr-un Telegram bot + Mini App, iar administratorul gestionează meniurile dintr-un panou React. Backend Flask + SQLite servește toate componentele.

## Structură
- `backend/` — `app.py` (API, 46 rute), `models.py` (8 modele), `bot.py` (proces Telegram separat), `scheduler.py` (4 joburi cron), `calculations.py` (numărarea porțiilor + rapoartele), `static/webapp/index.html` (Mini App vanilla JS).
- `frontend/` — React 19 + Vite, 5 pagini (Login, Dashboard, MenuManagement, UserManagement, Instructions).
- `docs/` — documentația detaliată (01..09). Pentru orice detaliu, mergi acolo întâi.

## Documentație (`docs/`)
- `01-concept.md` — problema, actorii, ziua tipică.
- `02-arhitectura.md` — cele 4 componente, fluxul datelor, rutarea.
- `03-model-date.md` — tabele, relații, invariante.
- `04-api.md` — toate cele 46 de endpoint-uri, cu nivel de acces.
- `05-functionalitati.md` — fiecare funcție, în detaliu.
- `06-cicluri-timp.md` — ciclul zilnic, cel săptămânal, joburile cron.
- `07-i18n.md` — unde trăiesc textele RO/RU și cum le sincronizezi.
- `08-operare.md` — variabile de mediu, Docker, nginx, teste.
- `09-probleme-cunoscute.md` — audit securitate + corectitudine, pe priorități.

## Comenzi
- Teste: `cd backend && python -m unittest discover -p 'test_*.py'` (NU pytest — nu e în requirements). **315 teste**, 99% acoperire.
- Acoperire: `python -m coverage run -m unittest discover -p 'test_*.py' && python -m coverage report` (config în `backend/.coveragerc`).
- Rulare locală: vezi skill `/meniubot-run`.
- Verificare end-to-end: `/meniubot-verify`.

## Skill-uri de proiect
- `/meniubot-run` — pornește stack-ul local și îl sondează că răspunde.
- `/meniubot-verify` — testează end-to-end fluxul zilnic după o schimbare.
- `/meniubot-i18n` — adaugi/schimbi texte RO/RU (trăiesc în 4 fișiere).
- `/meniubot-api-endpoint` — adaugi un endpoint nou după convențiile casei.
- `/meniubot-preflight` — checklist înainte de deploy în producție.

## Reguli (se aplică oricărei modificări)
- **Fus orar:** folosește `today_moldova()` / `now_moldova()` din `app.py`, NICIODATĂ `date.today()` sau `datetime.now()` gol. Tot business logic-ul e pe Europe/Chisinau.
- **Texte RO/RU:** trăiesc în 4 fișiere (`bot.py`, `app.py`, `static/webapp/index.html`, `calculations.py`). Modifici într-unul → verifici toate. Rulează `/meniubot-i18n`.
- **Migrații:** nu există Alembic. O coloană nouă se adaugă în `models.py` ȘI în dicționarul `new_cols` din `migrate_db()` (`app.py`).
- **Mesaje Telegram din backend:** doar prin `send_telegram_message()` — respectă stopul de urgență (`BotControl.is_enabled`).
- **FK:** SQLite nu impune chei străine. Adaugi un model cu FK către `User`/`Menu` → cureți-l manual în `delete_user()` / `delete_menu()`.
- **Limbi:** panoul de admin e doar în română. Mini App-ul și botul sunt RO+RU.
- **Auth non-admin:** endpoint-urile chemate de Mini App folosesc `@require_telegram` (headerul `X-Telegram-Init-Data`); cele chemate de procesul bot folosesc `@require_internal` (`X-Internal-Token`). Nu crede niciodată un `telegram_id` din corpul cererii — ia-l din `g.telegram_user["id"]`. Vezi `backend/auth.py`.

## Git
NU adăuga niciodată trailerul `Co-Authored-By: Claude ...` și nici vreo altă mențiune a lui Claude/Anthropic în mesajul de commit sau în corpul PR-urilor. Utilizatorul a cerut asta explicit.

## Bug-uri cunoscute care te vor mușca (vezi `docs/09-probleme-cunoscute.md`)
- `DELETE /api/users/<id>` dă 500 pentru orice user cu rând în `attendance` (P2.3, confirmat).
- `GET /api/report` dă 500 dacă un meniu a fost șters și au rămas selecții orfane (P2.2).
- Reminderele se trimit la fiecare 5 minute, fără deduplicare: ~19 mesaje/zi per utilizator care nu alege (P2.1).
