---
name: meniubot-i18n
description: Adaugă, schimbă sau verifică texte RO/RU în MeniuBot. Textele trăiesc în patru fișiere fără bibliotecă de i18n (bot.py, app.py, static/webapp/index.html, calculations.py), deci e ușor să traduci într-unul și să uiți de restul. Folosește-l la „schimbă mesajul", „adaugă un text", „traduce în rusă", „mesajul apare în română la rusofoni", „verifică traducerile".
---

# MeniuBot — texte RO/RU

Nu există `i18n`, nici fișiere de traduceri. Textele sunt dicționare Python și obiecte JS,
în **patru fișiere diferite**. Un mesaj schimbat într-un singur loc rămâne vechi în celelalte trei.

Fallback-ul e tăcut: o cheie lipsă în `ru` întoarce varianta `ro`. Nu crapă nimic — utilizatorul
rusofon vede doar text românesc. De aceea problemele trec neobservate.

## Întâi rulează checker-ul

```bash
python3 .claude/skills/meniubot-i18n/scripts/check_i18n.py --root .
```

Parsează toate cele patru fișiere (`ast` pentru Python, regex pe literale golite pentru JS) și
raportează cheile asimetrice. Iese cu `1` dacă lipsesc chei.

Starea de referință a repo-ului: **0 probleme, 6 avertismente**. Avertismentele sunt datorii
cunoscute, nu regresii — vezi mai jos. Dacă apar `✗`-uri, tu le-ai introdus.

Rulează-l din nou după orice modificare de text.

## Unde caut textul

| Textul apare… | Fișier | Structură |
|---|---|---|
| în mesajele botului (`/start`, `/menu`, `/guide`, reminder) | `backend/bot.py` | `TEXTS = {"ro": {...}, "ru": {...}}`, acces prin `t(lang, key)` |
| în mesajele trimise de API (confirmare, „mâncarea a sosit", închidere comenzi) | `backend/app.py` | 5 dicționare plate: `FOOD_ARRIVED_TEXTS`, `SELECTION_CONFIRM_TEXTS`, `SELECTION_NO_LUNCH_TEXTS`, `ORDERING_CLOSED_TEXTS`, `FEL_LABELS` |
| în Mini App | `backend/static/webapp/index.html` | `const TEXTS = { ro: {...}, ru: {...} }`, acces prin `tt(key)` |
| în raportul pentru furnizor | `backend/calculations.py` | `FEL_LABELS_RO` / `FEL_LABELS_RU` |
| în panoul de admin | `frontend/src/**` | hardcodat, **doar română** — panoul nu e multilingv |
| în meniuri și instrucțiuni | baza de date | coloane `_ru`: `name_ru`, `felul_1_ru`, `title_ru`, … |

Dacă nu găsești un text, `grep -rn "fragment" backend/ frontend/src/`. Ține minte că același mesaj
poate exista de două ori — o dată în `bot.py`, o dată în `app.py` — fiindcă îl trimit procese diferite.

## Reguli

**Amândouă limbile, mereu.** Adaugi o cheie în `ro` → o adaugi în `ru` în același commit.
Checker-ul te prinde dacă uiți.

**Nu adăuga ternare de limbă.** Tiparul greșit, care există deja în cod:

```python
f1_label = "Блюдо 1" if lang == "ru" else "Felul 1"       # app.py — nu imita
```
```js
btn.textContent = currentLang === 'ru' ? '⏳ Отправка...' : '⏳ Se trimite...';  // index.html — nu imita
```

Tiparul corect: pune textul în dicționar și cheamă `t(lang, key)` / `tt(key)`.

**Conținutul din bază nu se traduce în cod.** Numele meniurilor, felurile, instrucțiunile — toate
au coloane `_ru` și se editează din panou. Regula de fallback e:

```python
mname = menu.name
if lang == "ru" and menu.name_ru:      # doar dacă e nevid
    mname = menu.name_ru
```

Un `name_ru` gol înseamnă că rusofonii văd numele românesc. E intenționat, nu e bug.

**Emoji-urile sunt parte din text.** Toate mesajele au un ton cald și emoji la început de paragraf.
Păstrează registrul: prietenos, la persoana a doua, cu emoji, nu birocratic.

## Cele două ghiduri care divergă

Există **două** surse pentru „cum se comandă":

1. `TEXTS[lang]["guide"]` din `bot.py` — text static, trimis la `/guide` și după înregistrare.
   Conține ore hardcodate: „⏰ Program comenzi: 9:00 — 10:30".
2. Tabela `instructions` — pași cu imagini, editabili din panou, afișați la 📖 în Mini App.

Nimic nu le sincronizează. Dacă administratorul schimbă fereastra de remindere din Dashboard
(`BotControl.reminder_start` / `reminder_end`), textul din `bot.py` rămâne cu orele vechi.

Dacă utilizatorul se plânge că ghidul arată ore greșite, asta e cauza. Reparația reală: scoate orele
din text și interpolează-le din `GET /api/bot/status`.

## Avertismentele cunoscute (nu le „repara" din reflex)

Checker-ul raportează 6 avertismente pe repo-ul curat. Sunt datorie tehnică documentată în
[`docs/07-i18n.md`](../../../docs/07-i18n.md) și [`docs/09-probleme-cunoscute.md`](../../../docs/09-probleme-cunoscute.md#p39--configurație-hardcodată):

- antetele raportului (`TOTAL PORȚII`, `📊 DETALII COMENZI`) sunt hardcodate în română
- 1× `if lang == "ru"` în `bot.py` (mesajele de „bine ai revenit")
- 2× etichete inline în `app.py`
- 4× ternare de limbă în Mini App (`formatDate`, salut, buton de trimitere, alertă de eroare)
- ghidul duplicat, cu ore hardcodate

Curăță-le doar dacă utilizatorul cere asta explicit. Altfel, atenția e pe modificarea lui, nu pe
refactorizare nesolicitată.

## După modificare

1. `python3 .claude/skills/meniubot-i18n/scripts/check_i18n.py --root .` → 0 probleme
2. Dacă ai atins `calculations.py`: `cd backend && python -m unittest test_calculations -v`
   (testele verifică `TOTAL PORȚII` și antetele din raport — se rup dacă schimbi formatul)
3. Dacă ai atins un mesaj trimis de API: `/meniubot-verify`

## A treia limbă (engleză)

README-ul promite „RO/RU/EN". În cod engleza **nu există** — botul oferă două butoane.
Ar fi nevoie de: cheia `"en"` în cele patru dicționare, coloane `_en` în `menus` și `instructions`
(plus migrație în `migrate_db()` — vezi `/meniubot-api-endpoint`), al treilea buton în `start()`,
și o a treia listă nominală în raport.
