# 04 — Referință API

Bază: `/api`. Clienții cheamă `/meniubot/api` — un reverse proxy rescrie prefixul
(vezi [02-arhitectura.md](02-arhitectura.md#rutarea--partea-cea-mai-fragilă)).

**45 de endpoint-uri.**

## Niveluri de acces

Există patru:

- 🔒 **`@token_required` (JWT admin)** — antet `Authorization: Bearer <JWT>`. JWT HS256, valabil 24h,
  semnat cu `SECRET_KEY`. Payload-ul conține doar `sub` (username-ul de admin). **Nu există roluri.**
- 📱 **`initData` Telegram** — antet `X-Telegram-Init-Data` cu șirul semnat de Telegram. Serverul
  reverifică semnătura HMAC-SHA256 cu `TELEGRAM_BOT_TOKEN`, extrage `user.id` din payload-ul verificat
  și ignoră complet orice `telegram_id` din corpul cererii. Vezi [`backend/auth.py`](../backend/auth.py).
- 🤖 **Token intern** — antet `X-Internal-Token` cu secretul partajat `INTERNAL_API_TOKEN`. Doar
  procesul bot îl deține; comparația e în timp constant. Backend-ul și botul refuză să pornească fără el.
- 🌐 **Public** — nicio verificare. **8** din cele 45 de endpoint-uri.

`POST /api/bot/stop` și `POST /api/bot/start` cer 🔒 JWT admin **și** `ADMIN_PASSWORD` în corp
(a doua confirmare, comparată în timp constant cu `hmac.compare_digest`) — dar tot fără rate limiting.

> Endpoint-urile chemate de Mini App (📱) nu cred niciun `telegram_id` din corp: identitatea vine
> exclusiv din `initData`-ul verificat criptografic. Cele chemate de procesul bot (🤖) sunt izolate
> pe rețeaua internă cu token-ul partajat.
> Vezi [09-probleme-cunoscute.md](09-probleme-cunoscute.md#p0--securitate-critică).

## Parametrul `restaurant`

Valorile acceptate sunt `sezatoare` și `andys` (`Restaurant(value)`). Parsarea trece prin
`parse_restaurant()`, care întoarce `400` cu mesaj clar la o valoare invalidă.

Unde apare, semantica e uniformă:
- **absent / gol** → fără filtru, adică **ambele** restaurante — cu **o excepție**: `GET /api/report`,
  unde e **obligatoriu**;
- `POST /api/notify/food-arrived` acceptă în plus valoarea `all`.

## Autentificare

| | Endpoint | Descriere |
|---|---|---|
| 🌐 | `POST /api/auth/login` | `{username, password}` → `{token}`. Compară cu `ADMIN_USERNAME`/`ADMIN_PASSWORD` |

## Meniuri

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `GET /api/menus?restaurant=&day_of_week=&week_start=` | Implicit: săptămâna curentă. Sortat după `(restaurant, sort_order)` |
| 🔒 | `GET /api/menus/today` | Meniurile de azi, ambele restaurante (aprobate sau nu). Weekend → `[]` |
| 🌐 | `GET /api/menus/today/approved?restaurant=` | **Sursa Mini App-ului.** Doar `is_approved=True`. Fără `restaurant` → ambele. Weekend → `[]` |
| 🔒 | `POST /api/menus` | Creează. Acceptă `restaurant` (default `sezatoare`). La `andys` creează automat **3 `MenuOption` goale** |
| 🔒 | `PUT /api/menus/<id>` | Actualizare parțială, câmp cu câmp. **Nu** poate schimba `restaurant` |
| 🔒 | `DELETE /api/menus/<id>` | Șterge meniul, opțiunile lui (cascade) **și** toate selecțiile care îl referă prin oricare din cele 3 FK-uri sau prin `felul1_option_id` |
| 🔒 | `POST /api/menus/<id>/approve` | `is_approved = True` pentru un singur meniu |
| 🔒 | `POST /api/menus/approve-today` | Vezi mai jos |
| 🔒 | `POST /api/menus/reset-content` | Golește `felul_1/2`, `garnitura` (+`_ru`) **și opțiunile Andy's** pe toată săptămâna, ambele restaurante, și dez-aprobă. Structura rămâne. **Singura** cale de golire — nu există niciun job automat. Întoarce `{reset, options_reset}` |

### `POST /api/menus/approve-today`

```json
{ "restaurant": "sezatoare" }   // opțional; absent → aprobă AMBELE restaurante
```

Aprobă toate meniurile de azi ale restaurantului indicat, resetează `BotControl.update_required`,
apoi cheamă `notify_menu_ready()`: trimite „🍽 Meniul de azi e gata!" (RO/RU) tuturor utilizatorilor
**activi**, **neabsenți**, care **încă nu au ales** azi. Mesajul numește restaurantul aprobat.

Întoarce `{"approved": n, "notified": m}`. Dacă nu există niciun meniu de aprobat, nu trimite nimic.

## Opțiuni Andy's (Felul 1)

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `POST /api/menus/<menu_id>/options` | `{text, text_ru, sort_order?}` → `201` cu opțiunea. `sort_order` implicit = numărul de opțiuni existente |
| 🔒 | `PUT /api/menu-options/<id>` | `{text?, text_ru?, sort_order?}` — actualizare parțială |
| 🔒 | `DELETE /api/menu-options/<id>` | Șterge opțiunea **și** selecțiile care o referă prin `felul1_option_id` |

## Selecții

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `GET /api/selections?date=&restaurant=` | Implicit azi, ambele restaurante. Include `user`, `felul1_menu`, `felul2_menu`, `felul1_option` serializate |
| 📱 | `POST /api/selections` | **Scrierea principală.** Vezi mai jos |

### `POST /api/selections`

Cere antetul `X-Telegram-Init-Data`. Identitatea vine din `g.telegram_user["id"]`, extras din
`initData`-ul verificat — corpul **nu** conține `telegram_id`.

```jsonc
// Șezătoare — ambele feluri, din meniuri DIFERITE
{"restaurant": "sezatoare", "felul1_menu_id": 3, "felul2_menu_id": 4, "source": "webapp"}

// Șezătoare — doar Felul 1
{"restaurant": "sezatoare", "felul1_menu_id": 3, "source": "webapp"}

// Șezătoare — doar Felul 2
{"restaurant": "sezatoare", "felul2_menu_id": 4, "source": "webapp"}

// Andy's — business lunch + opțiunea de Felul 1. Felul 2 se adaugă automat.
{"restaurant": "andys", "felul1_menu_id": 7, "felul1_option_id": 12, "source": "webapp"}

// Fără prânz — restaurantul nu contează
{"fara_pranz": true, "source": "webapp"}
```

**Validări.** Toate întorc `400` cu mesaj în română, în afară de cele notate:

- `403` dacă `DailySettings.ordering_open = False` pentru azi;
- `401` dacă `initData` lipsește, e expirat sau are semnătură invalidă;
- `404` dacă utilizatorul din `initData` nu e înregistrat;
- `restaurant` lipsă sau invalid (când nu e `fara_pranz`);
- fiecare meniu referit trebuie să **existe**, să fie `is_approved=True`, să fie **al zilei de azi**
  (`day_of_week` + `week_start_date`) și să aparțină restaurantului indicat — altfel `400`;
- **Șezătoare:** cel puțin unul dintre `felul1_menu_id` / `felul2_menu_id`;
- **Andy's:** `felul1_menu_id` **și** `felul1_option_id` sunt obligatorii; opțiunea trebuie să aparțină
  acelui meniu; `felul2_menu_id` se setează automat = `felul1_menu_id`.

**Comportament.** Upsert pe `(user_id, today)` — a doua trimitere înlocuiește complet prima, inclusiv
restaurantul. `fel_selectat` se **derivă**, nu se citește din corp (vezi [03](03-model-date.md)).
`menu_id` (legacy) se populează cu `felul1_menu_id or felul2_menu_id`.

Dacă `source == "webapp"`, trimite **și** confirmarea pe Telegram, în limba utilizatorului, cu
restaurantul și felurile alese.

## Utilizatori

| | Endpoint | Descriere |
|---|---|---|
| 🤖 | `POST /api/users/register` | Upsert pe `telegram_id`. Doar botul (`X-Internal-Token`). O cerere fără `first_name` pentru un utilizator inexistent întoarce `200` fără să creeze |
| 📱🤖 | `GET /api/users/check/<telegram_id>` | `{registered: bool, user?}`. `initData` (doar propriul `id`, altfel `403`) SAU `X-Internal-Token` |
| 🔒 | `GET /api/users` | Toți utilizatorii |
| 🔒 | `GET /api/users/<id>/history` | Istoricul selecțiilor, descrescător. ⚠️ Bazat pe `menu_id` **legacy** — vezi [09](09-probleme-cunoscute.md) |
| 🔒 | `PUT /api/users/<id>` | `first_name`, `last_name`, `language`, `is_active` |
| 🔒 | `DELETE /api/users/<id>` | Curăță `selections` + `notification_logs`. ⚠️ **Nu** `attendance` → 500 |

## Raport

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `GET /api/report?restaurant=<sezatoare\|andys>&date=` | `restaurant` **OBLIGATORIU** — fără el, `400` |

Întoarce:

```json
{ "report_text": "…", "date": "2026-07-10", "restaurant": "sezatoare", "total": 21 }
```

- `total` = `TOTAL PORȚII` la Șezătoare, `TOTAL COMENZI` la Andy's.
- `date` invalid (nu `YYYY-MM-DD`) → `400`.
- Selecțiile `fara_pranz` sunt excluse.
- Un meniu șters lasă o selecție cu FK orfan; raportul **nu mai crapă** — sare peste partea lipsă
  (`_sezatoare_row` / `_andys_row` întorc rând gol, iar apelantul îl aruncă).

**Cele două rapoarte nu se combină niciodată.** Panoul le cere separat și le afișează în două carduri.
Formatul exact: [05-functionalitati.md](05-functionalitati.md#11-rapoartele-pentru-furnizori).

## Notificări

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `POST /api/notify/food-arrived` | `{"restaurant": "sezatoare"\|"andys"\|"all"}` — **obligatoriu**. Vezi mai jos |
| 🤖 | `GET /api/notify/pending-users` | Cine încă nu a ales. Doar botul (`X-Internal-Token`) — expune `telegram_id`-uri |

### `POST /api/notify/food-arrived`

Trei butoane în panou: **Șezătoare**, **Andy's**, **Toți**.

| `restaurant` | Cine primește |
|---|---|
| `sezatoare` | doar cei cu selecție de azi la Șezătoare |
| `andys` | doar cei de la Andy's |
| `all` | toți cei cu selecție de azi, orice restaurant |

În toate cazurile se sar: `fara_pranz`, utilizatorii inactivi, cei marcați absenți. Se scrie câte un
rând `NotificationLog(type=food_arrived)`. Mesajul (RO/RU) numește restaurantul.

**Efect secundar: dez-aprobă meniurile de azi — dar doar ale restaurantului notificat** (`all` →
ambele). Ciclul acelui restaurant s-a încheiat.

Întoarce `{"count": n}`. Lipsa `restaurant` sau o valoare necunoscută → `400`.

### `GET /api/notify/pending-users`

Întoarce `[]` — deci botul nu trimite nimic — dacă **oricare** dintre condiții e adevărată: botul e
oprit, e sărbătoare, e weekend, comenzile sunt închise, sau nu există **niciun** meniu aprobat azi
(numărat peste **ambele** restaurante).

## Control bot

| | Endpoint | Descriere |
|---|---|---|
| 🌐 | `GET /api/bot/status` | Citit de procesul bot și de Mini App |
| 🔒 | `POST /api/bot/stop` | JWT admin + `{password}` în corp. Stop de urgență — blochează **toate** mesajele |
| 🔒 | `POST /api/bot/start` | JWT admin + `{password}` în corp. Reactivează |
| 🔒 | `PUT /api/bot/settings` | `reminder_start`, `reminder_end`, `is_holiday`, `update_required` |

## Preluarea comenzilor

| | Endpoint | Descriere |
|---|---|---|
| 🌐 | `GET /api/ordering/status` | Starea de azi |
| 🔒 | `POST /api/ordering/close` | Închide **și** notifică pe cei care nu au ales (sar peste absenți). Întoarce `{sent_count}` |
| 🔒 | `POST /api/ordering/open` | Redeschide. Nu notifică |

## Prezență

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `GET /api/attendance?date=` | Toți utilizatorii activi + `is_present` (implicit `true`) |
| 🔒 | `POST /api/attendance` | `{user_id, is_present, date?}` |
| 🔒 | `POST /api/attendance/bulk` | `{updates: [{user_id, is_present}], date?}` |
| 🔒 | `GET /api/attendance/stats?start=&end=` | Implicit săptămâna curentă. Zilele fără rând se numără **prezent** |

## Mini App

| | Endpoint | Descriere |
|---|---|---|
| 🌐 | `GET /webapp` | Servește `static/webapp/index.html` |
| 📱 | `GET /api/webapp/my-selection` | Alegerea utilizatorului din `initData`. ⚠️ Întoarce doar `{has_selection, fel_selectat, menu_name}` — **fără** restaurant și fără feluri. Vezi [09](09-probleme-cunoscute.md) |
| 🌐 | `GET /api/webapp/ordering-status` | Variantă simplificată a `/api/ordering/status` |

## Instrucțiuni

| | Endpoint | Descriere |
|---|---|---|
| 🌐 | `GET /api/instructions` | Doar `is_active=True`, pentru Mini App |
| 🔒 | `GET /api/instructions/all` | Inclusiv inactive |
| 🔒 | `POST /api/instructions` | `multipart/form-data`, câmp `image` opțional |
| 🔒 | `PUT /api/instructions/<id>` | Acceptă **și** `multipart` (cu imagine), **și** JSON (fără) |
| 🔒 | `DELETE /api/instructions/<id>` | Șterge și fișierul imagine |
| 🔒 | `POST /api/instructions/<id>/remove-image` | Doar imaginea |
| 🌐 | `GET /api/static/uploads/<filename>` | Servește imaginile |
