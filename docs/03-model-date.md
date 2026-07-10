# 03 — Model de date

Șapte tabele, definite în [`backend/models.py`](../backend/models.py). SQLite.

```
   User ──1:N──▶ Selection ◀──N:1── Menu
    │  │
    │  ├──1:N──▶ Attendance
    │  └──1:N──▶ NotificationLog
    │
  (fără FK)
    │
 DailySettings   Instruction   BotControl
   (pe zi)       (conținut)    (rând unic)
```

## `users`

Angajații înregistrați prin bot. Nu conține administratorul — acela trăiește în variabile de mediu.

| Coloană | Tip | Note |
|---------|-----|------|
| `id` | int, PK | |
| `telegram_id` | bigint, **unique**, indexat | identitatea reală; tot API-ul public îl folosește |
| `first_name`, `last_name` | str(100) | din răspunsul la „cum te cheamă" (split pe primul spațiu) |
| `username` | str(100) | `@username` din Telegram, actualizat automat la interacțiune |
| `language` | str(5) | `"ro"` sau `"ru"` |
| `is_active` | bool | `False` → exclus din remindere și notificări |
| `registered_at` | datetime | **UTC** |

`last_name` poate fi șir gol dacă utilizatorul a scris un singur cuvânt.

## `menus`

Un rând per (meniu × zi × săptămână). Cu 4 șabloane și 5 zile ies **20 de rânduri pe săptămână**.

| Coloană | Tip | Note |
|---------|-----|------|
| `id` | int, PK | |
| `name`, `name_ru` | str(100) | „Lunch 1" / „Обед 1" |
| `day_of_week` | int | `0`=Luni … `4`=Vineri. **Nevalidat** la scriere |
| `week_start_date` | date, NOT NULL | luni-ul săptămânii; cheia de partiționare |
| `sort_order` | int | `0`=Lunch 1, `1`=Lunch 2, `2`=Dieta, `3`=Post |
| `felul_1`, `felul_1_ru` | str(255) | conținutul, completat de admin |
| `felul_2`, `felul_2_ru` | str(255) | |
| `garnitura`, `garnitura_ru` | str(255) | salată, plăcintă etc. |
| `is_approved` | bool | **poarta**: doar meniurile aprobate ajung la angajați |

Nu există constrângere de unicitate pe `(day_of_week, week_start_date, name)`. Un `POST /api/menus`
repetat creează duplicate.

## `selections`

Alegerea unui angajat pentru o zi.

| Coloană | Tip | Note |
|---------|-----|------|
| `user_id` | FK → `users.id`, NOT NULL | |
| `menu_id` | FK → `menus.id`, **nullable** | `NULL` când `fel_selectat = fara_pranz` |
| `fel_selectat` | enum | `felul1` \| `felul2` \| `ambele` \| `fara_pranz` |
| `date` | date, NOT NULL | default `date.today()` — ora **serverului**, nu Moldova |
| `selected_at` | datetime | default UTC, dar `app.py` scrie ora Moldovei |

**Invarianta centrală:** `UniqueConstraint(user_id, date)` — o singură selecție pe zi per om.
`POST /api/selections` face upsert manual, nu insert.

⚠️ `menu_id` e nullable și pentru `fara_pranz`, dar și când meniul referit a fost **șters**.
`DELETE /api/menus/<id>` nu curăță selecțiile care îl referă. Vezi [09](09-probleme-cunoscute.md).

## `attendance`

Cine e la birou azi. Absent = nu primește niciun mesaj și nu e numărat.

| Coloană | Tip | Note |
|---------|-----|------|
| `user_id` | FK → `users.id` | |
| `date` | date | |
| `is_present` | bool | |

`UniqueConstraint(user_id, date)`.

**Absența rândului înseamnă prezent.** Tot codul citește cu `attendance_map.get(u.id, True)` sau
construiește doar mulțimea absenților. Nu se scrie un rând per om per zi.

## `daily_settings`

Un rând per zi, creat **leneș** — abia când administratorul închide comenzile.

| Coloană | Tip | Note |
|---------|-----|------|
| `date` | date, **unique** | |
| `ordering_open` | bool | |
| `closed_at` | datetime | ora Moldovei |

Lipsa rândului = comenzile sunt deschise. Toate citirile tratează `None` ca `ordering_open=True`.

## `bot_control`

**Un singur rând, `id=1`**, creat la pornire dacă lipsește. Setări globale.

| Coloană | Default | Ce face |
|---------|---------|---------|
| `is_enabled` | `True` | Stop de urgență. `False` → `send_telegram_message()` blochează **tot** |
| `stopped_at`, `started_at` | `NULL` | audit |
| `reminder_start` | `"09:00"` | fereastra de remindere, `HH:MM` |
| `reminder_end` | `"10:30"` | |
| `is_holiday` | `False` | `True` → fără remindere azi |
| `update_required` | `False` | `True` → Mini App-ul afișează bannerul „aplicația a fost actualizată" |

Citit peste tot cu `BotControl.query.get(1)` — API vechi, depreciat în SQLAlchemy 2.x.

## `instructions`

Ghidul afișat în Mini App (butonul 📖). Administrat din pagina Instrucțiuni.

| Coloană | Note |
|---------|------|
| `title`, `title_ru` | |
| `content`, `content_ru` | text lung |
| `image_filename` | nume generat cu `uuid4().hex`, pe disc în `static/uploads/` |
| `sort_order` | ordinea pașilor |
| `is_active` | `False` → ascuns în Mini App, vizibil în admin |

Extensii acceptate: `png`, `jpg`, `jpeg`, `gif`, `webp`. Fără limită de dimensiune.

## `notification_logs`

| Coloană | Note |
|---------|------|
| `user_id` | FK |
| `type` | enum: `reminder` \| `food_arrived` |
| `sent_at` | **UTC** |

⚠️ Se scrie **doar** `food_arrived`. Valoarea `reminder` nu e folosită nicăieri în cod — de aceea
reminderele nu pot fi deduplicate. Vezi [09](09-probleme-cunoscute.md).

## Integritate referențială

SQLite nu impune FK-urile decât cu `PRAGMA foreign_keys=ON`, care nu e setat. Ștergerile sunt
manuale, iar acoperirea e incompletă:

| Ștergi | Se curăță | Rămâne orfan |
|--------|-----------|--------------|
| `User` | `Selection`, `NotificationLog` | **`Attendance`** |
| `Menu` | — | **`Selection`** (→ `menu_id` orfan) |
| `Instruction` | fișierul imagine | — |
