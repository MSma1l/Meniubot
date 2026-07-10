# 04 — Referință API

Bază: `/api`. Clienții cheamă `/meniubot/api` — un reverse proxy rescrie prefixul
(vezi [02-arhitectura.md](02-arhitectura.md#rutarea--partea-cea-mai-fragilă)).

## Niveluri de acces

Există patru:

- 🔒 **`@token_required` (JWT admin)** — antet `Authorization: Bearer <JWT>`. JWT HS256, valabil 24h,
  semnat cu `SECRET_KEY`. Payload-ul conține doar `sub` (username-ul de admin). **Nu există roluri.**
- 📱 **`initData` Telegram** — antet `X-Telegram-Init-Data` cu șirul semnat de Telegram. Serverul
  reverifică semnătura HMAC-SHA256 cu `TELEGRAM_BOT_TOKEN`, extrage `user.id` din payload-ul verificat
  și ignoră complet orice `telegram_id` din corpul cererii. Vezi [`backend/auth.py`](../backend/auth.py).
- 🤖 **Token intern** — antet `X-Internal-Token` cu secretul partajat `INTERNAL_API_TOKEN`. Doar
  procesul bot îl deține; comparația e în timp constant. Backend-ul și botul refuză să pornească fără el.
- 🌐 **Public** — nicio verificare. **8** din cele 43 de endpoint-uri.

`POST /api/bot/stop` și `POST /api/bot/start` cer acum 🔒 JWT admin **și** `ADMIN_PASSWORD` în corp
(a doua confirmare, comparată în timp constant cu `hmac.compare_digest`) — dar tot fără rate limiting.

> Endpoint-urile chemate de Mini App (📱) nu mai cred niciun `telegram_id` din corp: identitatea vine
> exclusiv din `initData`-ul verificat criptografic. Cele chemate de procesul bot (🤖) sunt izolate
> pe rețeaua internă cu token-ul partajat.
> Vezi [09-probleme-cunoscute.md](09-probleme-cunoscute.md#p0--securitate-critică).

## Autentificare

| | Endpoint | Descriere |
|---|---|---|
| 🌐 | `POST /api/auth/login` | `{username, password}` → `{token}`. Compară cu `ADMIN_USERNAME`/`ADMIN_PASSWORD` |

## Meniuri

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `GET /api/menus?day_of_week=&week_start=` | Implicit: săptămâna curentă. Sortat după `sort_order` |
| 🔒 | `GET /api/menus/today` | Meniurile de azi (toate, aprobate sau nu). Weekend → `[]` |
| 🌐 | `GET /api/menus/today/approved` | **Sursa Mini App-ului.** Doar `is_approved=True`. Weekend → `[]` |
| 🔒 | `POST /api/menus` | Creează. Fără validare pe `day_of_week`; permite duplicate |
| 🔒 | `PUT /api/menus/<id>` | Actualizare parțială, câmp cu câmp |
| 🔒 | `DELETE /api/menus/<id>` | ⚠️ Nu curăță `selections` care îl referă |
| 🔒 | `POST /api/menus/<id>/approve` | `is_approved = True` |
| 🔒 | `POST /api/menus/approve-today` | Aprobă toate meniurile de azi; resetează `update_required` |
| 🔒 | `POST /api/menus/reset-content` | Golește `felul_1/2`, `garnitura` (+`_ru`) pe toată săptămâna și dez-aprobă |

## Selecții

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `GET /api/selections?date=` | Implicit azi. Include `user` și `menu` serializate |
| 🔒 | `GET /api/selections/alerts` | Meniurile cu **număr impar** de `felul1` → nu se pot împerechea |
| 📱 | `POST /api/selections` | **Scrierea principală.** Vezi mai jos |

### `POST /api/selections`

Cere antetul `X-Telegram-Init-Data`. Identitatea vine din `g.telegram_user["id"]`, extras din
`initData`-ul verificat — corpul **nu** mai conține `telegram_id`.

```json
{ "menu_id": 42, "fel_selectat": "ambele", "source": "webapp" }
```

- `menu_id` este `null` când `fel_selectat = "fara_pranz"`.
- `401` dacă `initData` lipsește, e expirat sau are semnătură invalidă.
- Refuză cu `403` dacă `DailySettings.ordering_open = False` pentru azi.
- `404` dacă utilizatorul din `initData` nu e înregistrat; `400` dacă `fel_selectat` nu e din enum.
- Upsert pe `(user_id, today)` — a doua trimitere suprascrie prima.
- Dacă `source == "webapp"`, trimite **și** confirmarea pe Telegram, cu conținutul meniului ales,
  în limba utilizatorului.

## Utilizatori

| | Endpoint | Descriere |
|---|---|---|
| 🤖 | `POST /api/users/register` | Upsert pe `telegram_id`. Doar botul (`X-Internal-Token`). O cerere fără `first_name` pentru un utilizator inexistent întoarce acum `200` fără să creeze — nu mai dă 500 |
| 📱🤖 | `GET /api/users/check/<telegram_id>` | `{registered: bool, user?}`. `initData` (doar propriul `id`, altfel `403`) SAU `X-Internal-Token` |
| 🔒 | `GET /api/users` | Toți utilizatorii |
| 🔒 | `GET /api/users/<id>/history` | Istoricul complet al selecțiilor, descrescător |
| 🔒 | `PUT /api/users/<id>` | `first_name`, `last_name`, `language`, `is_active` |
| 🔒 | `DELETE /api/users/<id>` | Curăță `selections` + `notification_logs`. ⚠️ **Nu** `attendance` |

## Raport

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `GET /api/report?date=` | `{report_text, portions, date}`. Exclude `fara_pranz` |

`portions` = `{ "Lunch 1": {maxi, standard, felul1_count, felul2_count, ambele_count, sort_order, garnitura}, … }`

`report_text` este raportul gata de copiat pentru furnizor: total porții, detalii per meniu,
apoi lista nominală de două ori — o dată în română, o dată în rusă.

⚠️ Dă `500` dacă vreo selecție non-`fara_pranz` are `menu_id` orfan (meniu șters).

## Notificări

| | Endpoint | Descriere |
|---|---|---|
| 🔒 | `POST /api/notify/food-arrived` | Trimite „mâncarea a sosit" celor care au comandat, sunt activi și prezenți. **Efect secundar: dez-aprobă meniurile de azi.** Întoarce `{count}` |
| 🤖 | `GET /api/notify/pending-users` | Cine încă nu a ales. Doar botul (`X-Internal-Token`) — expune `telegram_id`-uri, deci nu mai e public |

`GET /api/notify/pending-users` întoarce `[]` — deci botul nu trimite nimic — dacă **oricare**
dintre condiții e adevărată: botul e oprit, e sărbătoare, e weekend, comenzile sunt închise,
sau nu există niciun meniu aprobat azi.

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
| 🔒 | `POST /api/ordering/open` | Redeschide |

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
| 📱 | `GET /api/webapp/my-selection` | Alegerea utilizatorului din `initData`. Query param-ul `telegram_id` a fost **eliminat** — nu mai poți citi alegerea altcuiva |
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
