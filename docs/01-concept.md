# 01 — Concept și idee

## Problema

Un birou comandă zilnic prânz de la doi furnizori. Fără sistem, procesul arată așa:
cineva întreabă pe chat cine ce vrea, adună răspunsurile manual, numără câte porții ies la fiecare
restaurant, sună furnizorii, apoi anunță pe toată lumea când sosește mâncarea. Se pierde timp,
se pierd comenzi, iar numărătoarea se face greșit.

MeniuBot automatizează exact acest lanț.

## Ideea centrală: două restaurante, o singură comandă pe om

Biroul comandă de la **două** restaurante, cu reguli de comandă complet diferite:

| | **La Șezătoare** | **Andy's** |
|---|---|---|
| Unitatea | meniuri (Lunch 1, Lunch 2, …) | business lunch-uri (Business Lunch 1, …) |
| Număr de meniuri | variabil — adminul adaugă/șterge | variabil — adminul adaugă/șterge |
| Felul 1 | textul `felul_1` al meniului | **N opțiuni** din tabela `menu_options` (implicit 3) |
| Felul 2 | textul `felul_2` al meniului | **fix**, inclus automat în business lunch |
| Ce alege angajatul | combinație liberă | obligatoriu **exact o** opțiune de Felul 1 |

**La Șezătoare, combinația e liberă.** Angajatul poate lua Felul 1 dintr-un meniu și Felul 2 din
**alt** meniu (ciorbă de la Lunch 1, friptură de la Lunch 2), sau doar un singur fel. Trebuie doar
să aleagă cel puțin unul dintre cele două.

**La Andy's, business lunch-ul e un pachet.** Felul 2 vine cu el, nu se alege. Angajatul alege doar
care dintre opțiunile de Felul 1 o vrea. Rezultatul e mereu Felul 1 + Felul 2.

**Un om, o comandă, un singur restaurant.** Constrângerea `UniqueConstraint(user_id, date)` o
garantează. Dacă cineva alege la Andy's după ce alesese la Șezătoare, noua alegere o **înlocuiește**
complet pe cea veche, inclusiv restaurantul.

### Numărătoarea: fiecare fel ales = 1 porție

Nu există conversii, nu există împerecheri, nu există porții Maxi/Standard. Se numără direct:

| Restaurant | Ce se numără |
|---|---|
| **Șezătoare** | fiecare Felul 1 ales = 1 porție; fiecare Felul 2 ales = 1 porție. `TOTAL PORȚII` = suma lor |
| **Andy's** | fiecare comandă = 1 comandă (= 1 Felul 1 + 1 Felul 2). `TOTAL COMENZI` = numărul de comenzi |

`fara_pranz` nu se numără deloc, la niciun restaurant.

Numărătoarea se face **separat pe fiecare meniu**. Un meniu fără nicio comandă nu apare în raport;
un fel cu zero comenzi se omite.

Regulile sunt implementate în [`backend/calculations.py`](../backend/calculations.py) —
`count_sezatoare()` și `count_andys()`, funcții pure, fără bază de date.

### Două rapoarte, niciodată combinate

Fiecare restaurant primește raportul lui. `GET /api/report` cere **obligatoriu** parametrul
`restaurant`; fără el întoarce `400`. Panoul afișează două rapoarte separate, fiecare cu propriile
butoane „Copiază" / „Descarcă". Un furnizor nu are ce face cu comenzile celuilalt.

## Actorii

**Angajatul.** Nu atinge niciodată panoul de admin. Interacționează exclusiv prin Telegram:
se înregistrează o dată (limbă + nume), apoi în fiecare dimineață primește un reminder, deschide
Mini App-ul, comută între cele două taburi de restaurant, alege, confirmă. Primește notificare când
sosește mâncarea de la restaurantul lui.

**Administratorul.** Un singur cont (`ADMIN_USERNAME` / `ADMIN_PASSWORD` din mediu — nu există
tabelă de admini). Completează meniurile săptămânii la ambele restaurante, le aprobă zilnic (pe un
restaurant sau pe amândouă), urmărește selecțiile în timp real, marchează prezența, închide
comenzile, generează cele două rapoarte, apasă „mâncarea a sosit".

**Furnizorii.** Doi, fără acces la sistem. Fiecare primește raportul lui, copiat sau descărcat de
administrator.

## Ziua tipică

```
 dimineața   Admin completează Felul 1 / Felul 2 la Șezătoare și opțiunile de Felul 1
             la Andy's, apoi APROBĂ (un restaurant sau ambele).
             → meniurile devin vizibile în Mini App
             → toți cei care încă nu au ales primesc „meniul de azi e gata"

 09:00–10:30 Botul trimite remindere, la fiecare 5 minute, celor care încă nu au ales.
             Angajații deschid Mini App-ul și aleg. Pot reveni și schimba alegerea
             (inclusiv restaurantul).

 ~10:30      Admin apasă „Închide preluarea comenzilor".
             → cei care încă nu au ales primesc mesaj că e prea târziu.

             Admin generează raportul Șezătoare → copiază → trimite furnizorului 1.
             Admin generează raportul Andy's    → copiază → trimite furnizorului 2.

 ~13:00      Mâncarea sosește. Admin apasă „Mâncarea a sosit" — trei butoane:
             Șezătoare / Andy's / Toți.
             → primesc notificare doar cei care au comandat de la restaurantul anunțat
             → meniurile de azi ale acelui restaurant se dez-aprobă automat
```

Detaliile fiecărui pas: [05-functionalitati.md](05-functionalitati.md).
Ce se întâmplă peste noapte și în weekend: [06-cicluri-timp.md](06-cicluri-timp.md).

## Principii de design vizibile în cod

**Aprobarea este poarta.** Un meniu necompletat sau neaprobat nu ajunge niciodată la angajat.
`GET /api/menus/today/approved` filtrează pe `is_approved=True`, iar dacă nu există niciun meniu
aprobat, botul nu trimite remindere deloc. Nimeni nu e deranjat degeaba.

**Aprobarea vorbește.** `POST /api/menus/approve-today` trimite, imediat după aprobare, un mesaj
tuturor celor care încă nu au ales azi. Nu mai trebuie să aștepte reminderul următor.

**Prezența taie zgomotul.** Un angajat marcat absent nu primește nici reminder, nici notificarea
„mâncarea a sosit", nici mesajul de închidere a comenzilor, nici anunțul de aprobare.

**Stop de urgență.** `BotControl.is_enabled` este un întrerupător global verificat în
`send_telegram_message()`. Când e oprit, **niciun** mesaj nu pleacă, indiferent de ce buton se apasă.

**O selecție pe zi.** Constrângerea de unicitate `(user_id, date)` garantează asta la nivel de bază
de date. A doua trimitere suprascrie prima (upsert), nu adaugă un rând — și poate schimba și
restaurantul.

**`fel_selectat` e un rezumat, nu o alegere.** Angajatul nu mai bifează „vreau Felul 1". El alege
meniuri și feluri; backend-ul **derivă** `fel_selectat` (`felul1` / `felul2` / `ambele` /
`fara_pranz`) la scriere. Coloana rămâne pentru compatibilitate și pentru filtrele rapide.

**Meniurile se reportează.** Luni dimineață structura săptămânii se creează copiind săptămâna
precedentă — inclusiv opțiunile de Felul 1 ale business lunch-urilor Andy's — ca administratorul să
nu rescrie de la zero.
