# 06 — Cicluri de timp

Aplicația are două ceasuri: unul zilnic (aprobă → comandă → livrează) și unul săptămânal
(creează structura → completează → golește). Ambele rulează pe `Europe/Chisinau`.

## Ciclul zilnic

```
 02:00 (doar luni)  ── seed_weekly_menus     structura săptămânii noi
 02:01 (doar luni)  ── reset_menu_content    conținut golit, tot dez-aprobat
        │
 dimineața          ── ADMIN completează Felul 1/2 și APROBĂ
        │              ▸ meniurile devin vizibile în Mini App
        │              ▸ reminderele se deblochează
        │
 09:00 ──┐
         │  bot: reminder_job la fiecare 5 min
         │  ▸ celor activi, prezenți, fără selecție
 10:30 ──┘
        │
 ~10:30             ── ADMIN „Închide preluarea comenzilor"
        │              ▸ POST /api/selections → 403
        │              ▸ mesaj celor care nu au ales
        │
        │           ── ADMIN „Generează raport" → copiază → furnizor
        │
 ~13:00             ── ADMIN „Mâncarea a sosit"
        │              ▸ notificare celor care au comandat
        │              ▸ EFECT SECUNDAR: meniurile de azi se dez-aprobă
        │
 23:30              ── unapprove_past_days(include_today=True)
                       plasă de siguranță: dez-aprobă tot ce a trecut, inclusiv azi
```

Weekend: `day_of_week > 4` scurtcircuitează `GET /api/menus/today`, `/api/menus/today/approved`
și `/api/notify/pending-users`. Nu se trimite nimic, nu se afișează nimic.

## Ciclul săptămânal

Cheia de partiționare este `Menu.week_start_date` — **luni-ul** săptămânii, calculat cu
`d - timedelta(days=d.weekday())`.

O săptămână completă înseamnă **20 de rânduri** în `menus`: 4 șabloane × 5 zile.

Șabloanele implicite, folosite doar când nu există nicio săptămână anterioară de copiat:

| `sort_order` | `name` | `name_ru` |
|---|---|---|
| 0 | Lunch 1 | Обед 1 |
| 1 | Lunch 2 | Обед 2 |
| 2 | Dieta | Диета |
| 3 | Post | Пост |

## Cele cinci joburi cron

Definite în [`scheduler.py`](../backend/scheduler.py), pornite din `run.py`.

| Când | Job | Ce face |
|------|-----|---------|
| Luni 02:00 | `seed_weekly_menus` | Creează cele 20 de rânduri pentru săptămâna nouă, copiind **doar structura** (nume, ordine, zi) din săptămâna trecută. No-op dacă există deja |
| Luni 02:01 | `reset_menu_content` | Golește `felul_1/2`, `garnitura` (+`_ru`) și pune `is_approved=False` pe toată săptămâna |
| Luni 06:00 | `cleanup_previous_week` | Șterge selecțiile de săptămâna trecută (luni–vineri) |
| Vineri 23:59 | `cleanup_previous_week` | Același job. Vineri seara șterge tot săptămâna **dinainte** |
| Zilnic 23:30 | `unapprove_past_days(include_today=True)` | Dez-aprobă meniurile zilelor trecute, inclusiv ziua care tocmai s-a încheiat |

`cleanup_previous_week` rulează de două ori pe săptămână intenționat: cel de luni este plasa de
siguranță pentru cazul în care containerul era oprit vineri seara. Ambele șterg **săptămâna
precedentă**, nu cea curentă — numele funcției e corect, comentariul din cod („clean up this week's
selections") nu.

Efectul net: în bază se păstrează selecțiile de maximum ~o săptămână și jumătate.

## Ce se întâmplă la pornire

Două lucruri, în ordinea asta:

**1. La importul modulului `app`** (deci și când pornește `run.py`, și la fiecare worker gunicorn):

```python
db.create_all()
migrate_db()          # ALTER TABLE pentru coloanele lipsă (users, menus)
migrate_bot_control() # idem pentru bot_control
seed_default_menus()  # creează săptămâna curentă dacă lipsește
# creează BotControl(id=1) dacă lipsește
```

**2. În `init_scheduler()`**, după ce joburile sunt înregistrate:

```python
seed_weekly_menus(app, db)                        # no-op, seed-ul deja rulat
unapprove_past_days(app, db, include_today=False) # curăță aprobările vechi
```

> Există două funcții de seed care nu fac același lucru. `seed_default_menus` (în `app.py`) copiază
> **și conținutul** meniurilor din săptămâna trecută; `seed_weekly_menus` (în `scheduler.py`) copiază
> **doar structura**. Prima câștigă la pornire, a doua în cron-ul de luni. Rezultatul e totuși
> consistent, fiindcă `reset_menu_content` golește conținutul la 02:01. Dar duplicarea e o capcană
> pentru oricine modifică una fără cealaltă.

## Trei mecanisme de dez-aprobare

Se suprapun. E redundant, dar fiecare acoperă un scenariu:

| Mecanism | Când | Acoperă |
|----------|------|---------|
| `notify_food_arrived()` | la apăsarea butonului | ziua s-a încheiat funcțional, mâncarea a sosit |
| `unapprove_past_days` (cron 23:30) | zilnic | ziua s-a încheiat calendaristic, chiar dacă nimeni n-a apăsat butonul |
| `unapprove_past_days` (la pornire) | la restart | containerul a fost oprit peste noapte |
| `reset_menu_content` (cron luni 02:01) | săptămânal | săptămâna nouă începe curată |

În weekend, `unapprove_past_days` dez-aprobă **toate** zilele săptămânii, nu doar cele trecute.

## Fereastra de remindere

Nu e cron. Jobul `reminder_job` din bot rulează la fiecare 5 minute, **non-stop**, și decide singur
dacă are voie să trimită, comparând `now_md().time()` cu `BotControl.reminder_start` / `reminder_end`
(implicit `09:00`–`10:30`, editabile din Dashboard).

Deci: 288 de execuții pe zi, din care ~19 trimit efectiv mesaje.
