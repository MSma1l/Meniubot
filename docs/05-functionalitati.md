# 05 — Funcționalități

Fiecare funcție, cu locul din cod unde trăiește și comportamentul la margini.

---

## 1. Înregistrarea angajatului

**Cod:** [`bot.py`](../backend/bot.py) — `ConversationHandler`, stările `LANG` → `FULL_NAME`.

`/start` → botul cheamă `GET /api/users/check/<telegram_id>`.

**Dacă e deja înregistrat:** mesaj de bun-venit personalizat, în limba lui, cu butonul Mini App.
Conversația se încheie imediat.

**Dacă nu:** întrebare bilingvă („Alegeți limba / Выберите язык") → două butoane inline →
„cum te cheamă" → `POST /api/users/register`.

Numele se despică pe **primul spațiu**: `text.split(maxsplit=1)`. „Ion Popescu Vasile" devine
`first_name="Ion"`, `last_name="Popescu Vasile"`. Un singur cuvânt → `last_name` gol.

După înregistrare: mesaj de confirmare + ghidul complet + butonul Mini App.

### Actualizarea automată a `@username`

Un `MessageHandler(filters.ALL)` și un `CallbackQueryHandler` înregistrate în `group=-1` rulează
**înaintea** oricărui alt handler, la orice interacțiune. Trimit `POST /api/users/register` cu
`telegram_id` + `username`, cu un cache de o oră în `context.user_data["_username_checked"]`.

Eșecurile sunt înghițite (`except Exception: pass`). Pentru un utilizator neînregistrat care scrie
ceva înainte de `/start`, backend-ul dă 500 (vezi [09](09-probleme-cunoscute.md)) — silențios.

---

## 2. Gestionarea meniului săptămânal

**Cod:** [`MenuManagement.tsx`](../frontend/src/pages/MenuManagement.tsx).

Tab-uri Luni–Vineri. Pentru ziua selectată, `GET /api/menus?day_of_week=<n>` întoarce cele 4 meniuri
ale săptămânii curente. Fiecare are 8 câmpuri editabile, în grilă RO/RU:

`name` · `felul_1` · `felul_2` · `garnitura` — și perechile `_ru`.

„Salvează toate meniurile" face `PUT` în paralel pentru fiecare meniu (`Promise.all`). Nu e atomic:
dacă o cerere eșuează, restul rămân salvate.

„Resetează conținutul meniurilor" → `POST /api/menus/reset-content` golește textele pe **toată
săptămâna** (toate cele 20 de rânduri) și dez-aprobă tot. Structura (nume, ordine, zi) rămâne.

---

## 3. Aprobarea — poarta către angajați

Un meniu cu `is_approved = False` **nu există** pentru angajat. `GET /api/menus/today/approved`
filtrează, iar Mini App-ul afișează „Niciun meniu încă".

Mai mult: dacă azi **niciun** meniu nu e aprobat, `GET /api/notify/pending-users` întoarce `[]`,
deci botul nu trimite niciun reminder. Nimeni nu e deranjat pentru un meniu inexistent.

Două căi de aprobare:
- `POST /api/menus/<id>/approve` — un meniu (din pagina Gestionare Meniu)
- `POST /api/menus/approve-today` — toate cele 4 de azi (buton pe Dashboard). Resetează și
  `BotControl.update_required`.

Dez-aprobarea e automată — vezi [06-cicluri-timp.md](06-cicluri-timp.md).

---

## 4. Alegerea meniului (Mini App)

**Cod:** [`static/webapp/index.html`](../backend/static/webapp/index.html).

Ecranul se ramifică, în ordinea asta:

| Condiție | Ce vede angajatul |
|----------|-------------------|
| comenzi închise **și** a ales deja | alegerea lui, read-only |
| comenzi închise **și** nu a ales | „⏰ Comenzile s-au închis" |
| a ales deja | alegerea lui + butonul „Vreau să schimb" |
| niciun meniu aprobat | „🤔 Niciun meniu încă" |
| altfel | secțiunile de meniu + bara de confirmare |

Pentru fiecare meniu aprobat se randează un card cu iconiță (potrivită după numele meniului),
Felul 1 / Felul 2 / Garnitură, și trei butoane: `Felul 1`, `Felul 2`, `Felul 1 + Felul 2`.
Plus un buton global „🚫 Fără prânz", punctat, care deselectează orice meniu.

Selecția e **exclusivă**: un singur meniu, un singur fel. Bara de confirmare de jos se activează
abia când există o alegere validă, și arată rezumatul.

La confirmare → `POST /api/selections` cu `source: "webapp"` → ecran de succes → `tg.close()`
după 2,5 secunde. Flag-ul `sending` previne dublu-click.

„Vreau să schimb" **reverifică** starea comenzilor înainte de a redeschide selecția — între timp
administratorul poate fi închis preluarea.

Navigare: bară sticky sus, cu scroll-spy (`IntersectionObserver`) care evidențiază secțiunea vizibilă.
Tema urmează `tg.colorScheme` (light/dark). Tot textul dinamic trece prin `escHtml()`.

---

## 5. Reminderele

**Cod:** `bot.py` — `reminder_job` / `send_reminders`.

Jobul rulează la **fiecare 5 minute**, non-stop (`run_repeating(interval=300, first=10)`).
Filtrarea se face în interiorul funcției, în două straturi.

**Stratul 1 — în bot**, din `GET /api/bot/status`:
- botul oprit → ieșire
- `is_holiday` → ieșire
- weekend → ieșire
- ora curentă în afara `[reminder_start, reminder_end]` → ieșire

Fereastra implicită este **09:00–10:30**, configurabilă din Dashboard.

**Stratul 2 — în backend**, `GET /api/notify/pending-users` întoarce `[]` dacă:
botul e oprit, e sărbătoare, e weekend, comenzile sunt închise, sau nu există meniu aprobat azi.

Ce rămâne: utilizatorii `is_active`, fără selecție azi, nemarcați absenți. Fiecare primește un mesaj
cu buton Mini App.

> ⚠️ Nu există deduplicare. Un angajat care nu alege deloc primește un reminder la fiecare 5 minute
> pe toată fereastra — **19 mesaje** pe intervalul implicit. Tabela `notification_logs` are valoarea
> de enum `reminder`, dar nu e scrisă niciodată. Vezi [09](09-probleme-cunoscute.md#p2--reminderele-se-repetă-la-fiecare-5-minute).

---

## 6. Închiderea preluării comenzilor

**Cod:** `app.py` — `close_ordering()`.

`POST /api/ordering/close` creează (leneș) rândul `DailySettings` de azi cu `ordering_open=False`,
apoi notifică — selectiv:

- sare peste absenți
- sare peste cei care **au ales deja** (au primit deja confirmare)
- restului: mesaj că e prea târziu, cu îndrumare către `@CroweTM_Office`

Din acest moment `POST /api/selections` întoarce `403` pentru toată lumea, iar Mini App-ul afișează
ecranul de închidere.

`POST /api/ordering/open` redeschide. Nu trimite nicio notificare.

---

## 7. „Mâncarea a sosit"

**Cod:** `app.py` — `notify_food_arrived()`.

Un buton pe Dashboard, cu `confirm()` înainte. Trimite mesajul tuturor celor care:
au o selecție azi, aceasta nu e `fara_pranz`, sunt `is_active`, și nu sunt marcați absenți.

Scrie câte un rând `NotificationLog(type=food_arrived)` pentru fiecare.

> **Efect secundar important:** dez-aprobă toate meniurile de azi. Ciclul zilei s-a încheiat.
> Consecință: dacă apeși butonul din greșeală dimineața, meniurile dispar din Mini App și reminderele
> se opresc (nu mai există meniu aprobat). Reparația e manuală: reaprobi meniurile.

---

## 8. Prezența

**Cod:** [`Dashboard.tsx`](../frontend/src/pages/Dashboard.tsx) (grilă de checkbox-uri),
[`UserManagement.tsx`](../frontend/src/pages/UserManagement.tsx) (statistici).

Model implicit: **absența rândului înseamnă prezent**. Se scrie un rând doar când administratorul
debifează pe cineva.

Un absent este exclus din: remindere, notificarea „mâncarea a sosit", mesajul de închidere a comenzilor.
Nu este exclus din raport — dacă a apucat să comande înainte de a fi marcat absent, comanda lui
intră în calculul porțiilor.

`GET /api/attendance/stats` numără zilele lucrătoare din interval și tratează zilele fără rând ca
prezente: `days_present += business_days - days_present - days_absent`.

---

## 9. Stop de urgență („Stop Cran")

**Cod:** `app.py` — `is_bot_enabled()`, apelat din `send_telegram_message()`.

Buton roșu pe Dashboard → modal cu parola de administrator → `POST /api/bot/stop`.

Când `BotControl.is_enabled = False`, funcția `send_telegram_message()` întoarce `False` fără să
trimită nimic. Asta blochează **toate** mesajele care pleacă din backend: confirmări, notificarea
„mâncarea a sosit", mesajul de închidere.

În paralel, procesul bot își verifică singur starea în `send_reminders()` și nu trimite remindere.

Dashboard-ul afișează un banner roșu permanent și butonul de repornire.

> Endpoint-urile `/api/bot/stop` și `/api/bot/start` sunt **publice**, apărate doar de parola din
> corpul cererii, comparată necriptografic și fără rate limiting.

---

## 10. Sărbătoare și fereastra de remindere

Trei controale pe Dashboard, toate prin `PUT /api/bot/settings`:

- **`is_holiday`** — oprește reminderele pentru azi. Nu blochează selecțiile: cine vrea, poate comanda.
- **`reminder_start` / `reminder_end`** — două input-uri `type="time"`, salvate la fiecare `onChange`
  (deci un `PUT` pe fiecare tastă din selectorul de oră).
- **`update_required`** — afișează în Mini App un banner albastru „aplicația a fost actualizată,
  apasă aici". La click, banner-ul devine verde și cere `/start` în chat. Se resetează automat la
  `POST /api/menus/approve-today`.

---

## 11. Raportul pentru furnizor

**Cod:** [`calculations.py`](../backend/calculations.py) — `generate_report_text()`.

`GET /api/report` → Dashboard afișează textul într-un `<pre>`, cu butoane „Copiază" și „Descarcă .txt".

Structura raportului:

```
📅 2026-07-10
📍 str. Exemplu 123, Chișinău
━━━━━━━━━━━━━━━━━━━━━━━
LUNCH 1 MAXI (Felul 1 + Felul 2) — 5 porții
LUNCH 1 STANDARD (doar Felul 2) — 2 porții
DIETA MAXI (Felul 1 + Felul 2) — 1 porții
━━━━━━━━━━━━━━━━━━━━━━━
TOTAL PORȚII: 8

📊 DETALII COMENZI:
━━━━━━━━━━━━━━━━━━━━━━━
LUNCH 1: 9 comenzi
  Felul 1: 2 | Felul 2: 2 | Felul 1+2: 5 | Garnitură: salată de varză

👤 COMENZI PER PERSOANĂ (RO):
━━━━━━━━━━━━━━━━━━━━━━━
  Ion Popescu — Lunch 1 — Felul 1 + Felul 2

👤 ЗАКАЗЫ ПО ПЕРСОНАМ (RU):
━━━━━━━━━━━━━━━━━━━━━━━
  Ion Popescu — Обед 1 — Блюдо 1 + Блюдо 2
```

Lista nominală apare de două ori, în ambele limbi, fiindcă furnizorul e rusofon iar biroul e mixt.

Selecțiile `fara_pranz` sunt excluse complet. Meniurile sunt sortate după `sort_order`.

Logica de calcul e **pură** — fără bază de date, fără I/O — și e singura parte cu teste
([`test_calculations.py`](../backend/test_calculations.py), 12 teste).

---

## 12. Alerta „Felul 1 nepereche"

**Cod:** `app.py` — `get_selection_alerts()`.

Grupează selecțiile `felul1` pe meniu. Dacă numărul e **impar**, ultimul om nu are cu cine forma o
porție Maxi. Dashboard-ul afișează un card portocaliu cu meniul, numărul și numele oamenilor.

Administratorul rezolvă manual — cere cuiva să comande Felul 1 la același meniu, sau acceptă o
porție Standard în plus.

---

## 13. Instrucțiuni (ghidul din Mini App)

**Cod:** [`Instructions.tsx`](../frontend/src/pages/Instructions.tsx), servite la 📖 în Mini App.

Pași numerotați, cu titlu, text și imagine opțională, în RO și RU. Ordonați după `sort_order`,
filtrați după `is_active`.

Încărcarea imaginii: `multipart/form-data`, nume generat cu `uuid4().hex`, salvat în
`static/uploads/`. Imaginea veche se șterge la înlocuire. Extensii permise: `png jpg jpeg gif webp`.
**Fără limită de dimensiune** și fără verificarea conținutului real al fișierului.

Botul are și o comandă `/guide` care trimite un text **hardcodat** în `bot.py` — complet separat de
tabela `instructions`. Cele două ghiduri pot diverge. Vezi [07-i18n.md](07-i18n.md).
