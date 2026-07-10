# Documentație MeniuBot

Sistem de gestionare a prânzului corporativ: angajații își aleg meniul dintr-un Telegram Mini App,
administratorul gestionează meniurile și generează raportul de porții pentru furnizor.

## Cuprins

| # | Document | Ce găsești |
|---|----------|-----------|
| 01 | [Concept și idee](01-concept.md) | Problema rezolvată, actorii, ziua tipică |
| 02 | [Arhitectură](02-arhitectura.md) | Cele 4 componente, fluxul datelor, rutarea |
| 03 | [Model de date](03-model-date.md) | Tabele, relații, invariante |
| 04 | [Referință API](04-api.md) | Toate cele 43 de endpoint-uri, cu nivel de acces |
| 05 | [Funcționalități](05-functionalitati.md) | Fiecare funcție, în detaliu |
| 06 | [Cicluri de timp](06-cicluri-timp.md) | Ciclul zilnic, cel săptămânal, joburile cron |
| 07 | [Multilingv (RO/RU)](07-i18n.md) | Unde trăiesc textele și cum le sincronizezi |
| 08 | [Operare și deploy](08-operare.md) | Variabile de mediu, Docker, nginx, teste |
| 09 | [Probleme cunoscute](09-probleme-cunoscute.md) | Audit: securitate + corectitudine, pe priorități |

## Start rapid

```bash
cp .env.example .env      # completează TELEGRAM_BOT_TOKEN și SECRET_KEY
docker compose up --build
```

Panoul de administrare: `http://localhost:5173/meniubot_admin/` — login `admin` / `admin`.

> ⚠️ Mini App-ul **nu funcționează** fără un reverse proxy care mapează `/meniubot/api` → backend `/api`.
> Vezi [08-operare.md](08-operare.md#reverse-proxy-obligatoriu).

## Skill-uri de proiect

Repo-ul conține skill-uri Claude Code în `.claude/skills/`. Le invoci cu `/` în Claude Code:

| Skill | Când îl folosești |
|-------|-------------------|
| `/meniubot-run` | Pornești stack-ul local și îl verifici că răspunde |
| `/meniubot-verify` | Testezi end-to-end fluxul zilnic după o schimbare |
| `/meniubot-i18n` | Adaugi sau schimbi un text RO/RU (trăiesc în 4 fișiere) |
| `/meniubot-api-endpoint` | Adaugi un endpoint nou după convențiile casei |
| `/meniubot-preflight` | Checklist înainte de deploy în producție |
