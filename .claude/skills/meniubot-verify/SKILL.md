---
name: meniubot-verify
description: Verifică end-to-end fluxul zilnic MeniuBot (login → aprobare meniu → selecție → alerte → raport → închidere comenzi → stop bot) pornind un backend pe o bază de date temporară și lovind API-ul real. Folosește-l după orice modificare în backend/app.py, models.py, calculations.py sau scheduler.py, înainte de commit sau deploy. Se declanșează la „verifică", „testează că merge", „nu am stricat nimic", „smoke test", „merge fluxul?".
---

# MeniuBot — verificare end-to-end

Rulează fluxul real prin HTTP, nu doar testele unitare. `test_calculations.py` acoperă 12 cazuri din
`calculations.py` și **nimic altceva** — nici un endpoint, nici aprobarea, nici filtrarea reminderelor.
Acest skill acoperă restul.

Verifică 48 de aserțiuni pe lanțul complet: autentificare → editare și aprobare meniu → înregistrare
utilizatori → selecții cu upsert → **testele de securitate ale noului model de auth** → alerta
„Felul 1 nepereche" → raportul de porții → prezență → închiderea comenzilor → stopul de urgență →
sărbătoare.

**Noul model de autentificare.** După închiderea găurilor P0, rutele non-admin nu mai cred corpul
cererii. Scriptul semnează un `initData` Telegram valid (HMAC-SHA256 cu tokenul botului) prin
`make_init_data()` și îl trimite în headerul `X-Telegram-Init-Data` pe `/selections` și
`/webapp/my-selection`; folosește headerul `X-Internal-Token` pentru rutele procesului bot
(`/users/register`, `/notify/pending-users`, calea internă a lui `/users/check`); iar `bot/stop` și
`bot/start` cer JWT admin + parolă. Secțiunea „Securitate" verifică explicit că fără header, cu
semnătură greșită, cu initData falsificat sau cu initData al altui user se întorc 401/403.

## Reguli

**Niciodată pe producție.** Scriptul creează utilizatori, scrie selecții, închide comenzile și
oprește botul. `scripts/smoke.py` refuză un host care nu conține `localhost` sau `127.0.0.1`,
în afară de cazul cu `--force`. Nu folosi `--force` decât dacă utilizatorul cere explicit.

**Bază de date temporară.** Nu porni backend-ul pe baza reală. Trimite `DATABASE_URL` către un
fișier din scratchpad.

**Secretele sunt acum OBLIGATORII.** `app.py` ridică `RuntimeError` la pornire dacă lipsesc
`SECRET_KEY` sau `INTERNAL_API_TOKEN`, iar `SECRET_KEY` nu poate fi `dev-secret-key` ori
`your_secret_key`. Deci comanda de pornire trebuie să le seteze pe amândouă, plus
`TELEGRAM_BOT_TOKEN` — cu el se semnează `initData`-ul de test. Tokenul de bot dat scriptului
(`--bot-token`) trebuie să fie identic cu `TELEGRAM_BOT_TOKEN` al serverului, altfel semnătura nu se
verifică și selecțiile pică cu 401. La fel, `--internal-token` = `INTERNAL_API_TOKEN`.

**Tokenul de bot e fals, dar setat.** `TELEGRAM_BOT_TOKEN=test-bot-token` e suficient ca să semneze
initData; nu e un token real de la Telegram. `send_telegram_message()` va încerca să lovească API-ul
Telegram doar la confirmările cu `source="webapp"` (pe care scriptul nu le trimite) — la un token fals
întoarce `False` și scrie o eroare în log, fără să crape și fără să trimită mesaje reale.

**Weekend.** Sâmbăta și duminica, `/menus/today`, `/menus/today/approved` și `/notify/pending-users`
întorc `[]` prin design. Scriptul detectează asta, spune de ce, și iese cu 0. Nu încerca să-l forțezi.

## Procedură

### 1. Mediu

Dacă dependențele nu-s instalate în sistem, fă un venv în scratchpad:

```bash
SP="$CLAUDE_SCRATCHPAD"        # sau orice director temporar
python3 -m venv "$SP/venv"
"$SP/venv/bin/pip" install -q -r backend/requirements.txt
```

### 2. Pornește backend-ul pe o bază curată

```bash
rm -f "$SP/test.db"
cd backend
DATABASE_URL="sqlite:///$SP/test.db" \
SECRET_KEY=0123456789abcdef0123456789abcdef \
INTERNAL_API_TOKEN=test-internal-token \
TELEGRAM_BOT_TOKEN=test-bot-token \
ADMIN_USERNAME=admin ADMIN_PASSWORD=admin FLASK_PORT=5099 \
  "$SP/venv/bin/python" run.py > "$SP/server.log" 2>&1 &
```

`SECRET_KEY` trebuie să aibă ≥32 caractere și să nu fie un default periculos, altfel `app.py` refuză
să pornească. `INTERNAL_API_TOKEN` și `TELEGRAM_BOT_TOKEN` trebuie să coincidă cu `--internal-token`
și `--bot-token` din pasul 3.

Așteaptă să răspundă, nu dormi orbește:

```bash
for i in $(seq 1 20); do
  curl -sf http://localhost:5099/api/bot/status >/dev/null 2>&1 && break
  sleep 1
done
```

La import, `app.py` rulează `db.create_all()`, migrațiile și `seed_default_menus()`, deci baza goală
primește automat cele 20 de meniuri ale săptămânii. Nu trebuie să semănezi nimic manual.

### 3. Rulează

```bash
"$SP/venv/bin/python" .claude/skills/meniubot-verify/scripts/smoke.py \
  --base http://localhost:5099 --bot-token test-bot-token --internal-token test-internal-token
```

`--bot-token` și `--internal-token` trebuie să fie EXACT valorile `TELEGRAM_BOT_TOKEN` și
`INTERNAL_API_TOKEN` cu care ai pornit serverul. Implicitele scriptului sunt tocmai `test-bot-token`
și `test-internal-token`, deci dacă folosești comanda de pornire de mai sus poți omite ambele flag-uri.

### 4. Citește rezultatul

Ieșire `0` = totul verde. Orice `✗` → **citește `$SP/server.log`** pentru traceback-ul real înainte
de a trage concluzii. Un `500` de la Flask apare în script doar ca un cod de stare; cauza e în log.

```bash
grep -iE "error|traceback|IntegrityError" "$SP/server.log" | head
```

### 5. Oprește serverul

```bash
pkill -f "run.py" || true
```

## Eșecul așteptat

**`DELETE /users/<id>` pentru `SmokeUnu` pică cu 500.** Nu e o regresie a ta.

Este bug-ul P2.3 din [`docs/09-probleme-cunoscute.md`](../../../docs/09-probleme-cunoscute.md):
`delete_user()` curăță `selections` și `notification_logs`, dar nu `attendance`. SmokeUnu e marcat
absent la pasul „Prezență", deci capătă un rând în `attendance`, iar SQLAlchemy încearcă să pună
`NULL` într-o coloană `nullable=False`:

```
sqlite3.IntegrityError: NOT NULL constraint failed: attendance.user_id
```

SmokeDoi se șterge fără probleme, fiindcă n-a fost niciodată debifat. De aceea bug-ul a trecut
neobservat în producție: se manifestă doar pentru utilizatorii care au lipsit măcar o zi.

Testul e lăsat intenționat să pice. **Devine verde exact când bug-ul e reparat** — adaugă
`Attendance.query.filter_by(user_id=user.id).delete()` în `delete_user()`.

Deci: `47 trecute, 1 picate` = starea de referință a repo-ului azi (măsurată, nu inventată).
`48 trecute` = ai reparat P2.3. Orice altceva picat = regresie.

> Cifrele astea sunt valabile **doar pe o bază curată**. Dacă reutilizezi `test.db` de la o rulare
> anterioară, SmokeUnu a rămas în bază (n-a putut fi șters) și obții `46 trecute, 2 picate`.
> De aceea `rm -f "$SP/test.db"` de la pasul 2 nu e opțional.

## Ce nu acoperă

Conversația botului (`bot.py` — `/start`, `/menu`, `/guide`), joburile de scheduler, Mini App-ul,
și trimiterea efectivă de mesaje Telegram. Pentru astea nu există încă automatizare — verifică manual
sau extinde scriptul.

## Când extinzi scriptul

Adaugi un endpoint nou → adaugi o aserțiune. Tiparul e `check(eticheta, conditie, detaliu)`.
Curăță după tine în secțiunea „Curățenie". Ține scriptul rulabil pe o bază goală, fără fixture-uri
externe.
