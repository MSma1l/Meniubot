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

Eșecurile sunt înghițite (`except Exception: pass`).

---

## 2. Gestionarea meniului săptămânal

**Cod:** [`MenuManagement.tsx`](../frontend/src/pages/MenuManagement.tsx).

**Două niveluri de taburi:** întâi restaurantul (🍲 La Șezătoare / 🍛 Andy's), apoi ziua (Luni–Vineri).
Pentru combinația selectată, `GET /api/menus?restaurant=<r>&day_of_week=<n>` întoarce meniurile
săptămânii curente.

**Numărul de meniuri e variabil.** „Adaugă meniu" face `POST /api/menus` cu restaurantul activ și un
nume auto-incrementat (`Lunch 3` / `Business Lunch 2`); butonul de ștergere face `DELETE /api/menus/<id>`.

**Câmpurile diferă după restaurant:**

| | La Șezătoare | Andy's |
|---|---|---|
| `name` / `name_ru` | editabil | editabil |
| `felul_1` / `felul_1_ru` | editabil | **ascuns** — înlocuit de lista de opțiuni |
| Opțiuni de Felul 1 | — | listă editabilă, cu „Adaugă opțiune" / ștergere |
| `felul_2` / `felul_2_ru` | editabil | editabil, etichetat **„Felul 2 (inclus automat)"** |
| `garnitura` / `garnitura_ru` | editabil | editabil |

„Salvează toate meniurile" face `PUT` în paralel pentru fiecare meniu **și** `PUT /api/menu-options/<id>`
pentru fiecare opțiune modificată (`Promise.all`). Nu e atomic: dacă o cerere eșuează, restul rămân
salvate.

„Resetează conținutul meniurilor" → `POST /api/menus/reset-content` golește textele pe **toată
săptămâna**, la **ambele** restaurante, și dez-aprobă tot. Structura (nume, ordine, zi, restaurant)
rămâne.

> ⚠️ Reset-ul **nu** golește `menu_options`. Opțiunile de Felul 1 de la Andy's supraviețuiesc.
> Vezi [09](09-probleme-cunoscute.md).

---

## 3. Aprobarea — poarta către angajați

Un meniu cu `is_approved = False` **nu există** pentru angajat. `GET /api/menus/today/approved`
filtrează, iar Mini App-ul afișează „Niciun meniu încă".

Mai mult: dacă azi **niciun** meniu nu e aprobat (la niciun restaurant), `GET /api/notify/pending-users`
întoarce `[]`, deci botul nu trimite niciun reminder.

Două căi de aprobare:
- `POST /api/menus/<id>/approve` — un singur meniu (din pagina Gestionare Meniu);
- `POST /api/menus/approve-today` — toate meniurile de azi. Corpul `{restaurant}` e **opțional**:
  cu el aprobă un singur restaurant, fără el le aprobă pe **amândouă**. Resetează și
  `BotControl.update_required`.

### Anunțul de aprobare

`approve-today` cheamă `notify_menu_ready()` imediat după commit. Trimite „🍽 Meniul de azi e gata!"
(RO/RU, cu numele restaurantului aprobat) tuturor celor care sunt **activi**, **neabsenți** și
**încă nu au ales** azi. Cine a ales deja nu e deranjat.

Trece prin `send_telegram_message()`, deci stopul de urgență îl blochează. Răspunsul e
`{approved, notified}`.

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
| altfel | taburile de restaurant + secțiunile de meniu + bara de confirmare |

**Taburile de restaurant** sunt nivelul de sus. Tabul implicit e Șezătoare, dacă are meniuri aprobate
azi; altfel Andy's. Un tab fără meniuri aprobate afișează „Azi nu sunt meniuri aprobate la {restaurant}".

**La Șezătoare**, fiecare card de meniu are **două** butoane independente: `Felul 1` și `Felul 2`.
Angajatul poate apăsa `Felul 1` la Lunch 1 și `Felul 2` la Lunch 2 — combinația e liberă. Un al
doilea click pe același buton îl deselectează. Starea trăiește în `sezF1MenuId` / `sezF2MenuId`.

**La Andy's**, fiecare card de business lunch afișează Felul 2 (inclus, needitabil) și lista de
opțiuni de Felul 1. Angajatul apasă **exact una**; alegerea altei opțiuni, chiar de la alt business
lunch, o înlocuiește pe cea veche. Starea trăiește în `andyMenuId` + `andyOptionId`.

**Comutarea tabului nu resetează alegerea**, dar `hasSelection()` se evaluează pe tabul **activ** —
deci butonul de confirmare reflectă restaurantul din care trimiți.

Peste tot: butonul global „🚫 Fără prânz", punctat, care golește orice alegere de la ambele restaurante.

Bara de confirmare de jos se activează abia când există o alegere validă (Șezătoare: cel puțin un fel;
Andy's: meniu **și** opțiune) și arată rezumatul.

La confirmare → `buildPayload()` compune corpul potrivit restaurantului → `POST /api/selections` cu
`source: "webapp"` → ecran de succes → `tg.close()` după 2,5 secunde. Flag-ul `sending` previne
dublu-click.

„Vreau să schimb" **reverifică** starea comenzilor înainte de a redeschide selecția — între timp
administratorul poate fi închis preluarea.

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
botul e oprit, e sărbătoare, e weekend, comenzile sunt închise, sau nu există meniu aprobat azi
(numărat peste **ambele** restaurante).

Ce rămâne: utilizatorii `is_active`, fără selecție azi, nemarcați absenți. Fiecare primește un mesaj
cu buton Mini App.

> ⚠️ Nu există deduplicare. Un angajat care nu alege deloc primește un reminder la fiecare 5 minute
> pe toată fereastra — **19 mesaje** pe intervalul implicit. Tabela `notification_logs` are valoarea
> de enum `reminder`, dar nu e scrisă niciodată. Vezi [09](09-probleme-cunoscute.md#p21--reminderele-se-repetă-la-fiecare-5-minute).

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

## 7. „Mâncarea a sosit" — trei butoane

**Cod:** `app.py` — `notify_food_arrived()`.

Pe Dashboard sunt **trei** butoane, fiecare cu `confirm()` înainte: **Șezătoare**, **Andy's**, **Toți**.
Fiecare trimite `POST /api/notify/food-arrived` cu `{restaurant: "sezatoare" | "andys" | "all"}`.

Primesc mesajul cei care: au o selecție azi **la restaurantul anunțat**, aceasta nu e `fara_pranz`,
sunt `is_active`, și nu sunt marcați absenți. Textul (RO/RU) numește restaurantul.

Scrie câte un rând `NotificationLog(type=food_arrived)` pentru fiecare.

> **Efect secundar important:** dez-aprobă meniurile de azi — **doar ale restaurantului notificat**
> (`all` → ambele). Ciclul acelui restaurant s-a încheiat.
> Consecință: dacă apeși „Toți" din greșeală dimineața, meniurile dispar din Mini App și reminderele
> se opresc (nu mai există niciun meniu aprobat). Reparația e manuală: reaprobi meniurile.

---

## 8. Prezența

**Cod:** [`Dashboard.tsx`](../frontend/src/pages/Dashboard.tsx) (grilă de checkbox-uri),
[`UserManagement.tsx`](../frontend/src/pages/UserManagement.tsx) (statistici).

Model implicit: **absența rândului înseamnă prezent**. Se scrie un rând doar când administratorul
debifează pe cineva.

Un absent este exclus din: remindere, anunțul de aprobare a meniului, notificarea „mâncarea a sosit",
mesajul de închidere a comenzilor. Nu este exclus din raport — dacă a apucat să comande înainte de a
fi marcat absent, comanda lui intră în numărătoare.

`GET /api/attendance/stats` numără zilele lucrătoare din interval și tratează zilele fără rând ca
prezente: `days_present += business_days - days_present - days_absent`.

---

## 9. Stop de urgență („Stop Cran")

**Cod:** `app.py` — `is_bot_enabled()`, apelat din `send_telegram_message()`.

Buton roșu pe Dashboard → modal cu parola de administrator → `POST /api/bot/stop` (JWT admin **și**
parola în corp).

Când `BotControl.is_enabled = False`, funcția `send_telegram_message()` întoarce `False` fără să
trimită nimic. Asta blochează **toate** mesajele care pleacă din backend: confirmări, anunțul de
aprobare, notificarea „mâncarea a sosit", mesajul de închidere.

În paralel, procesul bot își verifică singur starea în `send_reminders()` și nu trimite remindere.

Dashboard-ul afișează un banner roșu permanent și butonul de repornire.

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

## 11. Rapoartele pentru furnizori

**Cod:** [`calculations.py`](../backend/calculations.py) — `build_sezatoare_report()` și
`build_andys_report()` (exportate și ca `generate_*`). Funcții **pure**: fără bază de date, fără I/O.
`app.py` face interogările și le pasează liste de dict-uri simple.

**Două rapoarte, niciodată combinate.** Dashboard-ul are două carduri, fiecare cu „Generează",
„Copiază" și „Descarcă .txt". Fiecare cheamă `GET /api/report?restaurant=<r>`.

### La Șezătoare — se numără porțiile

Fiecare fel ales = 1 porție. Un meniu fără nicio comandă nu apare; un fel cu 0 comenzi se omite.

```
🍲 LA ȘEZĂTOARE
📅 2026-07-10
📍 str. Exemplu 123, Chișinău
━━━━━━━━━━━━━━━━━━━━━━━
LUNCH 1
  Felul 1: Zeamă de găină — 7 porții
  Felul 2: Friptură — 5 porții
LUNCH 2
  Felul 1: Borș roșu — 3 porții
  Felul 2: Pilaf — 6 porții
━━━━━━━━━━━━━━━━━━━━━━━
TOTAL PORȚII: 21
```

`TOTAL PORȚII` = suma tuturor felurilor. Un om care a luat Felul 1 de la Lunch 1 și Felul 2 de la
Lunch 2 contribuie cu **câte o porție în fiecare meniu**.

### Andy's — se numără comenzile

Fiecare comandă = 1 Felul 1 + 1 Felul 2. Deci porțiile de Felul 2 = numărul de comenzi, iar suma
opțiunilor de Felul 1 = același număr.

```
🍛 ANDY'S
📅 2026-07-10
📍 str. Exemplu 123, Chișinău
━━━━━━━━━━━━━━━━━━━━━━━
BUSINESS LUNCH 1 — 12 comenzi
  Felul 2 (inclus): Pilaf cu carne — 12 porții
  Felul 1:
    Zeamă de găină — 5 porții
    Borș roșu — 4 porții
    Supă cremă de linte — 3 porții
━━━━━━━━━━━━━━━━━━━━━━━
TOTAL COMENZI: 12
```

Opțiunile de Felul 1 sunt sortate după `(sort_order, text)`.

### Lista nominală — comună ambelor

Ambele rapoarte se termină cu aceleași două blocuri, RO și RU, fiindcă furnizorul e rusofon iar
biroul e mixt:

```
👤 COMENZI PER PERSOANĂ (RO):
━━━━━━━━━━━━━━━━━━━━━━━
  Ion Popescu — Lunch 1: Zeamă de găină | Lunch 2: Pilaf

👤 ЗАКАЗЫ ПО ПЕРСОНАМ (RU):
━━━━━━━━━━━━━━━━━━━━━━━
  Ion Popescu — Обед 1: Куриная зама | Обед 2: Плов
```

Felurile luate din **același** meniu se grupează sub numele lui, o singură dată. La Andy's asta dă
`Business Lunch 1: Borș roșu + Pilaf cu carne`, nu meniul repetat de două ori.

### Acordul gramatical

`_numeral()` respectă româna: **1 porție**, **2 porții**, **20 DE porții**. Peste 19, limba cere „de"
înaintea substantivului — la fel pentru orice număr al cărui rest la 100 e 0 sau depășește 19
(*101 porții*, dar *120 de porții*). Aceleași reguli pentru `comandă` / `comenzi` (`_comenzi()`).

Selecțiile `fara_pranz` sunt excluse complet. Meniurile sunt sortate după `sort_order`, apoi după nume.

Logica e singura parte cu acoperire serioasă de teste:
[`test_calculations.py`](../backend/test_calculations.py), **25 de teste**.

---

## 12. Instrucțiuni (ghidul din Mini App)

**Cod:** [`Instructions.tsx`](../frontend/src/pages/Instructions.tsx), servite la 📖 în Mini App.

Pași numerotați, cu titlu, text și imagine opțională, în RO și RU. Ordonați după `sort_order`,
filtrați după `is_active`.

Încărcarea imaginii: `multipart/form-data`, nume generat cu `uuid4().hex`, salvat în
`static/uploads/`. Imaginea veche se șterge la înlocuire. Extensii permise: `png jpg jpeg gif webp`.
**Fără limită de dimensiune** și fără verificarea conținutului real al fișierului.

Botul are și o comandă `/guide` care trimite un text **hardcodat** în `bot.py` — complet separat de
tabela `instructions`. Cele două ghiduri pot diverge. Vezi [07-i18n.md](07-i18n.md).
