---
name: meniubot-api-endpoint
description: Ghidează adăugarea unui endpoint nou, model nou sau coloană nouă în backendul Flask al MeniuBot, respectând convențiile casei (token_required, fus orar Moldova, to_dict, migrațiile manuale în două locuri, curățarea FK-urilor). Folosește-l când utilizatorul cere „adaugă un endpoint", „endpoint nou", „adaugă o coloană", „coloană nouă", „model nou", „extinde API-ul", „adaugă o rută", „vreau o rută nouă în backend".
---

# Adăugare endpoint / model / coloană în backendul MeniuBot

Backendul este Flask + SQLAlchemy, un singur fișier de rute `backend/app.py` și modelele în `backend/models.py`. NU există Alembic — migrațiile sunt manuale și rulează la importul modulului. Citește secțiunile de mai jos înainte să scrii cod, apoi folosește checklist-ul final.

Fișiere-cheie (căi absolute):
- `/Users/ivanturcan/Desktop/Project/Meniubot/backend/app.py` — toate rutele, decoratorul `token_required`, helperele de timp, migrațiile.
- `/Users/ivanturcan/Desktop/Project/Meniubot/backend/models.py` — modelele SQLAlchemy.
- `/Users/ivanturcan/Desktop/Project/Meniubot/backend/calculations.py` — logica de porții/raport (are teste unit).
- `/Users/ivanturcan/Desktop/Project/Meniubot/frontend/src/api/client.ts` — clientul axios al panoului.
- `/Users/ivanturcan/Desktop/Project/Meniubot/backend/static/webapp/index.html` — Mini App (vanilla JS).
- `/Users/ivanturcan/Desktop/Project/Meniubot/docs/04-api.md` și `docs/03-model-date.md` — documentația care trebuie ținută la zi.

## Convențiile casei (obligatorii)

- **Rute**: `@app.route("/api/<resursa>", methods=["GET"])`, imediat sub el `@token_required` dacă e endpoint de admin. Prefixul e mereu `/api/...`. Nginx expune extern sub `/meniubot/api/...`, dar în cod scrii doar `/api/...`.
- **Autentificare**: `token_required` validează headerul `Authorization: Bearer <JWT>`, HS256 cu `app.config["SECRET_KEY"]`. Payload-ul conține doar `sub`. NU există roluri — orice token valid are acces complet. Nu inventa verificări de rol.
- **Fus orar**: NU folosi `date.today()` sau `datetime.now()`. Folosește helperele existente din `app.py`: `today_moldova()` și `now_moldova()` (ambele pe `ZoneInfo("Europe/Chisinau")`). În `scheduler.py` echivalentul e `today_md()`; în `bot.py` e `now_md()`.
- **Săptămâna**: `get_week_start(d=None)` întoarce luni-ul săptămânii (folosește `today_moldova()` dacă `d` e `None`).
- **Serializare**: fiecare model are metoda `to_dict()`. Endpoint-urile de listă întorc `jsonify([m.to_dict() for m in ...])`.
- **Update parțial**: câmp cu câmp, `if "camp" in data: obj.camp = data["camp"]`, apoi `db.session.commit()`. Vezi `update_menu()` ca model.
- **Erori**: `Model.query.get_or_404(id)` pentru obiect inexistent; `return jsonify({"error": "..."}), 400` pentru input invalid.
- **Weekend guard**: endpoint-urile „today" fac `if today.weekday() > 4: return jsonify([])`.
- **Trimitere mesaj Telegram**: folosește `send_telegram_message(chat_id, text)` din `app.py`. Verifică singură `is_bot_enabled()` (stopul de urgență) și `TELEGRAM_BOT_TOKEN`, întoarce `bool`. NU chema Telegram API direct.
- **Texte bilingve**: dicționare la nivel de modul `{"ro": "...", "ru": "..."}`, alese cu `.get(lang, X["ro"])`. Vezi skill-ul `/meniubot-i18n`.

## Exemplu complet: endpoint protejat + endpoint public

Un endpoint de admin (protejat) și unul public pentru bot/Mini App. Respectă `token_required`, `today_moldova()`, weekend guard și `to_dict()`.

```python
# În backend/app.py, în secțiunea de rute potrivită.

@app.route("/api/attendance/today", methods=["GET"])
@token_required
def get_attendance_today():
    """Lista prezenței pe ziua curentă (doar admin)."""
    today = today_moldova()
    if today.weekday() > 4:          # sâmbătă/duminică → gol
        return jsonify([])
    records = Attendance.query.filter_by(date=today).all()
    return jsonify([r.to_dict() for r in records])


@app.route("/api/attendance/count", methods=["GET"])
def get_attendance_count():
    """Endpoint PUBLIC (pentru bot): câte persoane sunt prezente azi."""
    today = today_moldova()
    if today.weekday() > 4:
        return jsonify({"count": 0})
    count = Attendance.query.filter_by(date=today, is_present=True).count()
    return jsonify({"count": count})
```

Endpoint POST cu upsert și validare de input. Exemplul folosește un model ipotetic `Feedback`, ca să
nu se ciocnească cu rutele existente:

```python
@app.route("/api/feedback", methods=["POST"])
@token_required
def upsert_feedback():
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"error": "user_id lipsește"}), 400

    today = today_moldova()
    record = Feedback.query.filter_by(user_id=user_id, date=today).first()
    if record is None:
        record = Feedback(user_id=user_id, date=today)
        db.session.add(record)
    if "rating" in data:
        record.rating = int(data["rating"])
    db.session.commit()
    return jsonify(record.to_dict()), 201
```

Tiparul de upsert (caută întâi, inserează doar dacă lipsește) e obligatoriu pentru orice model cu
`UniqueConstraint("user_id", "date")` — ca `Selection` și `Attendance`. Un `db.session.add()` direct
ciocnește constrângerea și ridică `IntegrityError` netratat, adică 500.

> **Numele funcției e endpointul Flask.** Două funcții cu același nume, chiar pe rute diferite, opresc
> aplicația la pornire cu `AssertionError: View function mapping is overwriting an existing endpoint
> function`. Înainte de a adăuga o rută, verifică:
> `grep -n 'def <nume_functie>' backend/app.py` și `grep -n '"/api/<ruta>"' backend/app.py`.

## Exemplu complet: coloană nouă

O coloană nouă se adaugă în **DOUĂ locuri**: în model (`models.py`) ȘI în dicționarul `new_cols` din `migrate_db()` (sau `migrate_bot_control()` dacă e pe tabela `bot_control`). Motiv: `db.create_all()` NU adaugă coloane la tabele care există deja — doar migrația manuală o face pentru bazele de date deja populate.

Exemplu: adăugăm `note` (text opțional) pe tabela `menus`.

1. În `backend/models.py`, în clasa `Menu` — adaugă coloana ȘI include-o în `to_dict()`:

```python
class Menu(db.Model):
    __tablename__ = "menus"
    # ... coloanele existente ...
    note = db.Column(db.String(255), default="")   # coloană nouă

    def to_dict(self):
        return {
            # ... câmpurile existente ...
            "note": self.note or "",
        }
```

2. În `backend/app.py`, în `migrate_db()`, adaugă intrarea în dicționarul `new_cols` al tabelei `menus`. Tipul se scrie ca SQL brut, la fel ca celelalte intrări:

```python
new_cols = {
    # ... intrările existente ...
    "note": "VARCHAR(255) DEFAULT ''",
}
```

`migrate_db()` citește coloanele existente cu `sqlalchemy.inspect(db.engine)` și execută `ALTER TABLE menus ADD COLUMN note VARCHAR(255) DEFAULT ''` prin `db.session.execute(text(...))` doar dacă lipsește. Idempotent — poți rula de câte ori.

Dacă adaugi coloana pe `bot_control`, pune-o în `new_cols` din `migrate_bot_control()`, nu în `migrate_db()`.

## Model complet nou

Un model complet nou **nu** are nevoie de migrație — `db.create_all()` (rulat la import în `app.py`) creează automat tabelele care lipsesc. Pași:

1. Definește clasa în `models.py` cu `__tablename__`, coloane, `to_dict()` și eventualele `UniqueConstraint`.
2. Importă modelul în `app.py`, în linia de import din `models` (alături de `User, Menu, Selection, ...`), altfel `NameError` la prima utilizare.
3. Dacă modelul are FK către `User` sau `Menu`, vezi obligatoriu secțiunea „Capcane" despre curățarea ștergerilor.

## Capcane (citește-le, sunt bug-uri reale în cod)

- **Fusul orar**: `date.today()` / `datetime.now()` dau ora serverului (UTC), nu ora Moldovei. Seara devreme sau dimineața devreme calculezi ziua greșită. Folosește mereu `today_moldova()` / `now_moldova()`.
- **Migrația în două locuri**: dacă adaugi coloana doar în model, merge pe o bază de date nouă (via `create_all`) dar dă `OperationalError: no such column` pe baza de producție deja existentă. Adaug-o și în `new_cols`.
- **FK-uri necurățate (SQLite nu impune FK)**: baza nu are `PRAGMA foreign_keys=ON`, deci ștergerile în cascadă NU se produc singure. Bug-uri confirmate care ilustrează problema:
  - `delete_user()` curăță `Selection` + `NotificationLog`, dar NU `Attendance` → 500 (bug P2.3).
  - `delete_menu()` nu curăță `Selection` → lasă `menu_id` orfan → `GET /api/report` dă 500 la `s.menu.name` (bug P2.2).
  - Dacă adaugi un model cu FK către `User` sau `Menu`, TREBUIE să-l cureți în `delete_user()` / `delete_menu()` cu `MojModel.query.filter_by(user_id=user.id).delete()` înainte de `db.session.delete(...)`, altfel adaugi încă un bug de același fel.
- **Endpoint public care primește `telegram_id`**: endpoint-urile publice nu au `token_required`. Un `telegram_id` primit în body NU e verificat — oricine poate trimite orice ID și acționa în numele altui utilizator (vezi `docs/09` P0.2). Nu adăuga endpoint-uri publice care mută stare pe baza unui `telegram_id` din body fără o verificare (minim: validează `initData` Telegram sau mută ruta sub `token_required`).
- **Lipsa validării inputului**: `request.get_json()` întoarce `None` dacă body-ul nu e JSON, iar accesul cu `data["camp"]` dă `KeyError` → 500. Folosește `request.get_json(silent=True) or {}` și `.get(...)`, apoi validează explicit câmpurile obligatorii cu `return jsonify({"error": "..."}), 400`.
- **Cursă la migrații sub multi-worker**: `app.py` rulează migrațiile la import. Momentan aplicația pornește cu `python run.py` (un singur proces), deci e ok. NU trece pe gunicorn cu mai mulți workeri fără să muți migrațiile într-un pas de startup separat — altfel două procese fac `ALTER TABLE` simultan.

## Checklist final

- [ ] Ruta scrisă cu `@app.route("/api/...")` + `@token_required` (sau conștient publică).
- [ ] Folosit `today_moldova()` / `now_moldova()`, niciun `date.today()` / `datetime.now()`.
- [ ] Endpoint „today" are weekend guard (`if today.weekday() > 4`).
- [ ] Modelul are `to_dict()`; endpoint-ul îl folosește.
- [ ] Input validat: `get_json(silent=True) or {}`, câmpuri obligatorii verificate, erori `400`.
- [ ] Coloană nouă → adăugată în model ȘI în `new_cols` (`migrate_db()` sau `migrate_bot_control()`) ȘI în `to_dict()`.
- [ ] Model nou → importat în `app.py`.
- [ ] Model nou cu FK către User/Menu → curățat în `delete_user()` / `delete_menu()`.
- [ ] Actualizat tabelul din `docs/04-api.md` (coloana de acces: 🔒 token_required / 🌐 public).
- [ ] Dacă ai atins modele → actualizat `docs/03-model-date.md`.
- [ ] Rulat `/meniubot-verify` (smoke test end-to-end) și adăugat o aserțiune nouă în `.claude/skills/meniubot-verify/scripts/smoke.py`.
- [ ] Dacă ai atins `calculations.py` → `cd backend && python -m unittest test_calculations -v`.
