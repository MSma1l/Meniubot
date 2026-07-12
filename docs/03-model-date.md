# 03 — Model de date

Opt tabele, definite în [`backend/models.py`](../backend/models.py). SQLite.

```
                      ┌──────────────┐
                      │  MenuOption  │  (opțiunile de Felul 1, Andy's)
                      └──────┬───────┘
                             │ N:1
   User ──1:N──▶ Selection ══╪══3 FK══▶ Menu ──1:N──▶ MenuOption
    │  │             │
    │  │             └── felul1_option_id ──▶ MenuOption
    │  ├──1:N──▶ Attendance
    │  └──1:N──▶ NotificationLog
    │
  (fără FK)
    │
 DailySettings   Instruction   BotControl
   (pe zi)       (conținut)    (rând unic)
```

`Selection` are **trei** chei străine către `menus` (`menu_id` legacy, `felul1_menu_id`,
`felul2_menu_id`) plus una către `menu_options`. Vezi capcana de la finalul secțiunii `selections`.

## Enum-ul `Restaurant`

```python
class Restaurant(enum.Enum):
    sezatoare = "sezatoare"
    andys = "andys"
```

`db.Enum(Restaurant)` stochează **numele** membrului ca text (`'sezatoare'` / `'andys'`) — de aceea
migrațiile folosesc `VARCHAR(20) DEFAULT 'sezatoare'`.

## `users`

Angajații înregistrați prin bot. Nu conține administratorul — acela trăiește în variabile de mediu.

| Coloană | Tip | Note |
|---------|-----|------|
| `id` | int, PK | |
| `telegram_id` | bigint, **unique**, indexat | identitatea reală; tot API-ul o folosește |
| `first_name`, `last_name` | str(100) | din răspunsul la „cum te cheamă" (split pe primul spațiu) |
| `username` | str(100) | `@username` din Telegram, actualizat automat la interacțiune |
| `language` | str(5) | `"ro"` sau `"ru"` |
| `is_active` | bool | `False` → exclus din remindere și notificări |
| `registered_at` | datetime | **UTC** |

`last_name` poate fi șir gol dacă utilizatorul a scris un singur cuvânt.

## `menus`

Un rând per (meniu × zi × săptămână × restaurant). Numărul de meniuri e **variabil**: adminul poate
adăuga și șterge. Șabloanele implicite dau 3 meniuri × 5 zile = **15 rânduri pe săptămână**
(Lunch 1, Lunch 2 la Șezătoare; Business Lunch 1 la Andy's).

| Coloană | Tip | Note |
|---------|-----|------|
| `id` | int, PK | |
| `restaurant` | enum, NOT NULL, indexat | `sezatoare` (default) \| `andys` |
| `name`, `name_ru` | str(100) | „Lunch 1" / „Обед 1"; „Business Lunch 1" / „Бизнес Ланч 1" |
| `day_of_week` | int | `0`=Luni … `4`=Vineri. **Nevalidat** la scriere |
| `week_start_date` | date, NOT NULL | luni-ul săptămânii; cheia de partiționare |
| `sort_order` | int | ordinea în cadrul restaurantului |
| `felul_1`, `felul_1_ru` | str(255) | **doar Șezătoare.** La Andy's e NEFOLOSIT — opțiunile stau în `menu_options` |
| `felul_2`, `felul_2_ru` | str(255) | Șezătoare: felul 2 al meniului. Andy's: felul 2 **fix**, inclus automat |
| `garnitura`, `garnitura_ru` | str(255) | salată, plăcintă etc. |
| `is_approved` | bool | **poarta**: doar meniurile aprobate ajung la angajați |

`Menu.to_dict()` include `"restaurant"` și `"options"` (lista opțiunilor serializate — goală la
Șezătoare).

Nu există constrângere de unicitate pe `(restaurant, day_of_week, week_start_date, name)`. Un
`POST /api/menus` repetat creează duplicate.

## `menu_options`

Opțiunile de **Felul 1** ale unui business lunch Andy's. De regulă 3 (`ANDYS_DEFAULT_OPTIONS`), dar
adminul poate adăuga sau șterge oricâte. La Șezătoare tabela rămâne goală.

| Coloană | Tip | Note |
|---------|-----|------|
| `id` | int, PK | |
| `menu_id` | FK → `menus.id`, NOT NULL, indexat | business lunch-ul căruia îi aparține |
| `text`, `text_ru` | str(255) | denumirea felului |
| `sort_order` | int | ordinea de afișare |

Relația de pe `Menu` are `cascade="all, delete-orphan"`, deci ștergerea unui meniu îi ia cu ea
opțiunile — **singura** curățare automată din tot modelul.

Un business lunch creat prin `POST /api/menus` cu `restaurant: "andys"` primește automat 3 opțiuni
**goale**, pe care adminul le completează.

## `selections`

Alegerea unui angajat pentru o zi. O comandă, dintr-un singur restaurant.

| Coloană | Tip | Note |
|---------|-----|------|
| `user_id` | FK → `users.id`, NOT NULL | |
| `restaurant` | enum, NOT NULL | `sezatoare` (default) \| `andys`. La `fara_pranz` se forțează `sezatoare` |
| `felul1_menu_id` | FK → `menus.id`, nullable | Șezătoare: meniul de la care vine Felul 1 (sau `NULL`). Andy's: **business lunch-ul ales** |
| `felul1_option_id` | FK → `menu_options.id`, nullable | Șezătoare: mereu `NULL`. Andy's: opțiunea de Felul 1 aleasă (**obligatorie**) |
| `felul2_menu_id` | FK → `menus.id`, nullable | Șezătoare: meniul de la care vine Felul 2 (sau `NULL`). Andy's: **același** business lunch |
| `menu_id` | FK → `menus.id`, nullable | **legacy.** Populat cu `felul1_menu_id or felul2_menu_id`, ca `/api/users/<id>/history` să meargă |
| `fel_selectat` | enum, NOT NULL | **rezumat derivat**, nu o alegere directă |
| `date` | date, NOT NULL | default `date.today()` — ora **serverului**, nu Moldova |
| `selected_at` | datetime | default UTC, dar `app.py` scrie ora Moldovei |

### `fel_selectat` e derivat, nu citit din corp

`POST /api/selections` **ignoră** orice `fel_selectat` din corpul cererii și îl calculează la scriere:

| Ce s-a ales | `fel_selectat` |
|---|---|
| `fara_pranz` | `fara_pranz` |
| Felul 1 **și** Felul 2 | `ambele` |
| doar Felul 1 | `felul1` |
| doar Felul 2 | `felul2` |

**Andy's e întotdeauna `ambele`** — Felul 2 vine cu pachetul.

**Invarianta centrală:** `UniqueConstraint(user_id, date)` — o singură selecție pe zi per om.
`POST /api/selections` face upsert manual, nu insert. A doua trimitere înlocuiește **complet**
alegerea, inclusiv restaurantul.

### ⚠️ Capcana celor trei chei străine

`Selection` are trei FK-uri către `menus`. SQLAlchemy nu mai poate deduce singur pe care coloană să
facă join și aruncă `AmbiguousForeignKeysError` la prima interogare. De aceea **toate** relațiile
sunt declarate explicit:

```python
# pe Menu:
selections = db.relationship("Selection", foreign_keys="Selection.menu_id",
                             backref="menu", lazy="dynamic")
# pe Selection:
felul1_menu   = db.relationship("Menu", foreign_keys=[felul1_menu_id])
felul2_menu   = db.relationship("Menu", foreign_keys=[felul2_menu_id])
felul1_option = db.relationship("MenuOption", foreign_keys=[felul1_option_id])
```

Dacă adaugi un al patrulea FK către `menus`, trebuie să-i dai și lui `foreign_keys=`. Fără asta,
aplicația nu mai pornește.

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

## Migrații

Nu există Alembic. O coloană nouă se adaugă în **două** locuri: în `models.py` **și** în dicționarele
`new_cols` din `migrate_db()` ([`app.py`](../backend/app.py)), care execută `ALTER TABLE`.

Migrația către modelul cu două restaurante adaugă:

```python
# tabela menus
"restaurant": "VARCHAR(20) DEFAULT 'sezatoare'"

# tabela selections
"restaurant":       "VARCHAR(20) DEFAULT 'sezatoare'",
"felul1_menu_id":   "INTEGER",
"felul1_option_id": "INTEGER",
"felul2_menu_id":   "INTEGER",
```

Tabela `menu_options` se creează singură prin `db.create_all()` — nu are nevoie de `ALTER TABLE`.

**Backfill.** Rulează **o singură dată**, imediat după ce coloanele apar (`if added_selection_columns:`),
niciodată la porniri ulterioare — deci nu poate suprascrie date reale. Toate comenzile vechi devin
comenzi Șezătoare, cu felurile legate din vechiul `menu_id`:

```sql
UPDATE menus      SET restaurant = 'sezatoare' WHERE restaurant IS NULL;
UPDATE selections SET restaurant = 'sezatoare' WHERE restaurant IS NULL;
UPDATE selections SET felul1_menu_id = menu_id
  WHERE fel_selectat IN ('felul1','ambele') AND felul1_menu_id IS NULL;
UPDATE selections SET felul2_menu_id = menu_id
  WHERE fel_selectat IN ('felul2','ambele') AND felul2_menu_id IS NULL;
```

## Integritate referențială

SQLite nu impune FK-urile decât cu `PRAGMA foreign_keys=ON`, care nu e setat. Ștergerile sunt
manuale, iar acoperirea e **aproape** completă:

| Ștergi | Se curăță | Rămâne orfan |
|--------|-----------|--------------|
| `User` | `Selection`, `NotificationLog` | **`Attendance`** → `DELETE` dă 500. Vezi [09](09-probleme-cunoscute.md) |
| `Menu` | `MenuOption` (cascade) + **toate** `Selection`-urile care îl referă, prin `menu_id`, `felul1_menu_id`, `felul2_menu_id` sau `felul1_option_id` | — |
| `MenuOption` | `Selection`-urile care o referă prin `felul1_option_id` | — |
| `Instruction` | fișierul imagine | — |

`delete_menu()` construiește un `db.or_(...)` peste toate cele patru condiții. Fără el, o selecție
rămasă cu FK orfan ar rupe raportul zilei — exact în momentul în care e nevoie de el.
