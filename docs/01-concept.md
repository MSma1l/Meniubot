# 01 — Concept și idee

## Problema

Un birou comandă zilnic prânz de la un furnizor extern. Fără sistem, procesul arată așa:
cineva întreabă pe chat cine ce vrea, adună răspunsurile manual, calculează câte porții ies,
sună furnizorul, apoi anunță pe toată lumea când sosește mâncarea. Se pierde timp, se pierd comenzi,
iar calculul porțiilor se face greșit.

MeniuBot automatizează exact acest lanț.

## Ideea centrală: porția nu e egală cu comanda

Furnizorul nu vinde „ce a ales fiecare om". Vinde **porții**, de două tipuri:

- **Maxi** = Felul 1 + Felul 2 împreună
- **Standard** = un singur fel

Un angajat poate alege doar Felul 1 (doar ciorbă). Dar furnizorul nu livrează jumătăți de porție.
Deci **doi oameni care aleg amândoi doar Felul 1, la același meniu, se combină într-o singură porție Maxi**.

Această conversie este inima aplicației. Totul în jur — botul, panoul, notificările — există ca să
alimenteze acest calcul cu date corecte, la timp.

Regulile complete, implementate în [`backend/calculations.py`](../backend/calculations.py):

| Ce a ales angajatul | Cum se numără |
|---------------------|---------------|
| Felul 1 + Felul 2 (`ambele`) | 1 porție **Maxi** |
| doar Felul 2 (`felul2`) | 1 porție **Standard** |
| doar Felul 1 (`felul1`) × 2 | se combină → 1 porție **Maxi** |
| doar Felul 1 (`felul1`) × 1 rămas fără pereche | 1 porție **Standard** |
| `fara_pranz` | nu se numără deloc |

Calculul se face **separat pe fiecare meniu** (Lunch 1, Lunch 2, Dieta, Post). Doi oameni care aleg
Felul 1 la meniuri diferite **nu** se combină.

### Consecința operațională: alerta „nepereche"

Când într-un meniu rămâne un număr **impar** de selecții `felul1`, ultimul om nu are pereche.
Panoul afișează o alertă (`GET /api/selections/alerts`) ca administratorul să intervină manual —
de obicei convingând pe cineva să comande Felul 1 la același meniu.

## Actorii

**Angajatul.** Nu atinge niciodată panoul de admin. Interacționează exclusiv prin Telegram:
se înregistrează o dată (limbă + nume), apoi în fiecare dimineață primește un reminder, deschide
Mini App-ul, alege meniul, confirmă. Primește notificare când sosește mâncarea.

**Administratorul.** Un singur cont (`ADMIN_USERNAME` / `ADMIN_PASSWORD` din mediu — nu există
tabelă de admini). Completează meniurile săptămânii, le aprobă zilnic, urmărește selecțiile în timp
real, marchează prezența, închide comenzile, generează raportul pentru furnizor, apasă „mâncarea a sosit".

**Furnizorul.** Nu are acces la sistem. Primește raportul text, copiat sau descărcat de administrator.

## Ziua tipică

```
 dimineața   Admin completează Felul 1 / Felul 2 pentru azi și le APROBĂ.
             → abia acum meniurile devin vizibile în Mini App.

 09:00–10:30 Botul trimite remindere, la fiecare 5 minute, celor care încă nu au ales.
             Angajații deschid Mini App-ul și aleg. Pot reveni și schimba alegerea.

 ~10:30      Admin apasă „Închide preluarea comenzilor".
             → cei care încă nu au ales primesc mesaj că e prea târziu.

             Admin generează raportul → copiază → trimite furnizorului.

 ~13:00      Mâncarea sosește. Admin apasă „Mâncarea a sosit".
             → toți cei care au comandat (și sunt prezenți) primesc notificare.
             → meniurile zilei se dez-aprobă automat.
```

Detaliile fiecărui pas: [05-functionalitati.md](05-functionalitati.md).
Ce se întâmplă peste noapte și în weekend: [06-cicluri-timp.md](06-cicluri-timp.md).

## Principii de design vizibile în cod

**Aprobarea este poarta.** Un meniu necompletat sau neaprobat nu ajunge niciodată la angajat.
`GET /api/menus/today/approved` filtrează pe `is_approved=True`, iar dacă nu există niciun meniu
aprobat, botul nu trimite remindere deloc. Nimeni nu e deranjat degeaba.

**Prezența taie zgomotul.** Un angajat marcat absent nu primește nici reminder, nici notificarea
„mâncarea a sosit", nici mesajul de închidere a comenzilor.

**Stop de urgență.** `BotControl.is_enabled` este un întrerupător global verificat în
`send_telegram_message()`. Când e oprit, **niciun** mesaj nu pleacă, indiferent de ce buton se apasă.

**O selecție pe zi.** Constrângerea de unicitate `(user_id, date)` garantează asta la nivel de bază
de date. A doua trimitere suprascrie prima (upsert), nu adaugă un rând.

**Meniurile se reportează.** Luni dimineață structura săptămânii se creează copiind săptămâna
precedentă, ca administratorul să nu rescrie de la zero numele meniurilor.
