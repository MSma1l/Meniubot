"""
Logica de raport pentru cele două restaurante (Șezătoare + Andy's).

Funcții PURE: fără DB, fără I/O, fără Flask. `app.py` face interogările și
pregătește listele de dict-uri simple descrise mai jos.

Nu mai există porții Maxi/Standard: fiecare fel ales = 1 porție.

────────────────────────────────────────────────────────────────────────
FORMA DATELOR (contractul cu app.py)
────────────────────────────────────────────────────────────────────────

`rows` pentru ȘEZĂTOARE — o intrare per selecție (NU per fel).
Combinație liberă: felul 1 poate veni dintr-un meniu, felul 2 din altul;
oricare dintre cele două perechi poate lipsi (cheie absentă sau None).

    {
      # felul 1 (opțional)
      "felul1_menu": "Lunch 1",          # numele meniului (RO)
      "felul1_menu_ru": "Обед 1",        # opțional, fallback pe felul1_menu
      "felul1_text": "Zeamă de găină",   # Menu.felul_1
      "felul1_text_ru": "Куриная зама",  # opțional, fallback pe felul1_text
      "sort_order_1": 0,                 # Menu.sort_order al meniului felului 1

      # felul 2 (opțional)
      "felul2_menu": "Lunch 2",
      "felul2_menu_ru": "Обед 2",
      "felul2_text": "Pilaf",            # Menu.felul_2
      "felul2_text_ru": "Плов",
      "sort_order_2": 1,
    }

`rows` pentru ANDY'S — o intrare per selecție. Fiecare comandă are OBLIGATORIU
un felul 2 (fix, inclus în business lunch) și exact o opțiune de felul 1.

    {
      "menu": "Business Lunch 1",             # numele business lunch-ului (RO)
      "menu_ru": "Бизнес Ланч 1",             # opțional
      "sort_order": 0,                        # Menu.sort_order
      "felul2_text": "Pilaf cu carne",        # Menu.felul_2 (fix)
      "felul2_text_ru": "Плов с мясом",       # opțional
      "felul1_text": "Zeamă de găină",        # MenuOption.text (aleasă)
      "felul1_text_ru": "Куриная зама",       # opțional
      "felul1_option_sort": 0,                # MenuOption.sort_order (pentru ordonare)
    }

`persons` (același format pentru ambele restaurante) — lista nominală finală:

    {
      "name": "Ion Popescu",
      "sort_order": 0,                        # ordinea în listă (ex. sort_order-ul meniului)
      "items": [
        {"menu": "Lunch 1", "menu_ru": "Обед 1",
         "text": "Zeamă de găină", "text_ru": "Куриная зама"},
        {"menu": "Lunch 2", "menu_ru": "Обед 2",
         "text": "Pilaf", "text_ru": "Плов"},
      ],
    }

Un `items` gol produce doar numele persoanei (fără feluri).
"""

from collections import OrderedDict

SEPARATOR = "━━━━━━━━━━━━━━━━━━━━━━━"

FEL_LABELS_RO = {
    "felul1": "Felul 1",
    "felul2": "Felul 2",
    "ambele": "Felul 1 + Felul 2",
    "fara_pranz": "Fără prânz",
}

FEL_LABELS_RU = {
    "felul1": "Блюдо 1",
    "felul2": "Блюдо 2",
    "ambele": "Блюдо 1 + Блюдо 2",
    "fara_pranz": "Без обеда",
}

RESTAURANT_LABELS_RO = {
    "sezatoare": "La Șezătoare",
    "andys": "Andy's",
}

RESTAURANT_LABELS_RU = {
    "sezatoare": "Ла Шезэтоаре",
    "andys": "Энди'с",
}

RESTAURANT_EMOJI = {
    "sezatoare": "🍲",
    "andys": "🍛",
}

# Titlul din capul raportului (admin → doar RO, majuscule)
RESTAURANT_HEADERS = {
    "sezatoare": "🍲 LA ȘEZĂTOARE",
    "andys": "🍛 ANDY'S",
}


def _numeral(count, singular, plural):
    """Acord românesc: 1 porție, 2 porții, 20 DE porții.

    Peste 19, româna cere „de" înaintea substantivului — la fel pentru orice
    număr al cărui rest la 100 e 0 sau depășește 19 (101 porții, dar 120 DE porții).
    """
    if count == 1:
        return f"1 {singular}"
    rest = count % 100
    if count >= 20 and (rest == 0 or rest > 19):
        return f"{count} de {plural}"
    return f"{count} {plural}"


def _portii(count):
    return _numeral(count, "porție", "porții")


def _comenzi(count):
    return _numeral(count, "comandă", "comenzi")


def _text(row, key, fallback_key=None):
    """Valoarea unei chei, cu fallback pe altă cheie și pe string gol."""
    value = row.get(key)
    if value:
        return value
    if fallback_key:
        return row.get(fallback_key) or ""
    return ""


# ──────────────────────────────────────────────────────────────────────
# Numărare (folosită și de Dashboard prin API)
# ──────────────────────────────────────────────────────────────────────

def count_sezatoare(rows):
    """
    Numără porțiile pe meniu și pe fel pentru Șezătoare.

    Fiecare fel ales = 1 porție. Un meniu apare în rezultat doar dacă are
    cel puțin o comandă (la felul 1, la felul 2, sau la ambele).

    Returns:
        {menu_name: {"name_ru": str, "sort_order": int,
                     "felul1": {"text": str, "text_ru": str, "count": int},
                     "felul2": {"text": str, "text_ru": str, "count": int}}}
        Un fel fără comenzi are count == 0 (și e omis din raport).
    """
    result = {}

    def bucket(menu_name):
        if menu_name not in result:
            result[menu_name] = {
                "name_ru": "",
                "sort_order": 0,
                "felul1": {"text": "", "text_ru": "", "count": 0},
                "felul2": {"text": "", "text_ru": "", "count": 0},
            }
        return result[menu_name]

    for row in rows or []:
        menu1 = row.get("felul1_menu")
        if menu1:
            entry = bucket(menu1)
            entry["sort_order"] = row.get("sort_order_1", entry["sort_order"]) or 0
            if not entry["name_ru"]:
                entry["name_ru"] = _text(row, "felul1_menu_ru") or menu1
            fel = entry["felul1"]
            fel["count"] += 1
            if not fel["text"]:
                fel["text"] = _text(row, "felul1_text")
                fel["text_ru"] = _text(row, "felul1_text_ru", "felul1_text")

        menu2 = row.get("felul2_menu")
        if menu2:
            entry = bucket(menu2)
            entry["sort_order"] = row.get("sort_order_2", entry["sort_order"]) or 0
            if not entry["name_ru"]:
                entry["name_ru"] = _text(row, "felul2_menu_ru") or menu2
            fel = entry["felul2"]
            fel["count"] += 1
            if not fel["text"]:
                fel["text"] = _text(row, "felul2_text")
                fel["text_ru"] = _text(row, "felul2_text_ru", "felul2_text")

    return result


def count_andys(rows):
    """
    Numără comenzile pe business lunch pentru Andy's.

    Fiecare comandă = 1 felul 1 (opțiune aleasă) + 1 felul 2 (fix).
    Deci porțiile de felul 2 == numărul de comenzi, iar suma opțiunilor de
    felul 1 == același număr.

    Returns:
        {menu_name: {"name_ru": str, "sort_order": int, "orders": int,
                     "felul2": {"text": str, "text_ru": str, "count": int},
                     "felul1_options": [{"text": str, "text_ru": str,
                                         "count": int, "sort_order": int}, ...]}}
        `felul1_options` e sortată după sort_order, apoi după text.
    """
    result = {}
    options = {}  # menu_name -> OrderedDict[text] = {...}

    for row in rows or []:
        menu_name = row.get("menu")
        if not menu_name:
            continue

        if menu_name not in result:
            result[menu_name] = {
                "name_ru": "",
                "sort_order": 0,
                "orders": 0,
                "felul2": {"text": "", "text_ru": "", "count": 0},
                "felul1_options": [],
            }
            options[menu_name] = OrderedDict()

        entry = result[menu_name]
        entry["sort_order"] = row.get("sort_order", entry["sort_order"]) or 0
        if not entry["name_ru"]:
            entry["name_ru"] = _text(row, "menu_ru") or menu_name
        entry["orders"] += 1

        fel2 = entry["felul2"]
        fel2["count"] += 1
        if not fel2["text"]:
            fel2["text"] = _text(row, "felul2_text")
            fel2["text_ru"] = _text(row, "felul2_text_ru", "felul2_text")

        opt_text = _text(row, "felul1_text")
        opt = options[menu_name].get(opt_text)
        if opt is None:
            opt = {
                "text": opt_text,
                "text_ru": _text(row, "felul1_text_ru", "felul1_text"),
                "count": 0,
                "sort_order": row.get("felul1_option_sort", 0) or 0,
            }
            options[menu_name][opt_text] = opt
        opt["count"] += 1

    for menu_name, entry in result.items():
        entry["felul1_options"] = sorted(
            options[menu_name].values(),
            key=lambda o: (o["sort_order"], o["text"]),
        )

    return result


# ──────────────────────────────────────────────────────────────────────
# Lista nominală (comună ambelor rapoarte)
# ──────────────────────────────────────────────────────────────────────

def _person_lines(persons):
    """Blocul final RO + RU cu comenzile per persoană. [] dacă `persons` e gol."""
    if not persons:
        return []

    ordered = sorted(persons, key=lambda p: (p.get("sort_order", 0) or 0, p.get("name", "")))

    def render(person, menu_key, menu_fallback, text_key, text_fallback):
        # Group by menu, so an Andy's order (one felul-1 + one felul-2, both from
        # the same business lunch) reads "Business Lunch 1: Bors + Pilaf cu carne"
        # instead of naming the menu twice.
        grouped = []          # [(menu, [text, ...])] — insertion order preserved
        for item in person.get("items") or []:
            menu = item.get(menu_key) or item.get(menu_fallback) or ""
            text = item.get(text_key) or item.get(text_fallback) or ""
            if not menu and not text:
                continue
            for entry in grouped:
                if entry[0] == menu:
                    entry[1].append(text)
                    break
            else:
                grouped.append((menu, [text]))

        parts = []
        for menu, texts in grouped:
            texts = [t for t in texts if t]
            if menu and texts:
                parts.append(f"{menu}: {' + '.join(texts)}")
            elif menu or texts:
                parts.append(menu or " + ".join(texts))

        name = person.get("name", "")
        if not parts:
            return f"  {name}"
        return f"  {name} — {' | '.join(parts)}"

    lines = ["", "👤 COMENZI PER PERSOANĂ (RO):", SEPARATOR]
    for person in ordered:
        lines.append(render(person, "menu", "menu", "text", "text"))

    lines += ["", "👤 ЗАКАЗЫ ПО ПЕРСОНАМ (RU):", SEPARATOR]
    for person in ordered:
        lines.append(render(person, "menu_ru", "menu", "text_ru", "text"))

    return lines


# ──────────────────────────────────────────────────────────────────────
# Rapoarte
# ──────────────────────────────────────────────────────────────────────

def build_sezatoare_report(rows, report_date, office_address, persons=None):
    """
    Raportul text pentru Șezătoare.

    Args:
        rows: listă de dict-uri în forma „ȘEZĂTOARE" documentată sus.
        report_date: str, ex. "2026-07-10"
        office_address: str
        persons: listă opțională pentru lista nominală (vezi docstring-ul modulului)

    Returns:
        str
    """
    counts = count_sezatoare(rows)
    total = 0

    lines = [
        RESTAURANT_HEADERS["sezatoare"],
        f"📅 {report_date}",
        f"📍 {office_address}",
        SEPARATOR,
    ]

    ordered = sorted(counts.keys(), key=lambda name: (counts[name]["sort_order"], name))
    for menu_name in ordered:
        entry = counts[menu_name]
        fel1 = entry["felul1"]
        fel2 = entry["felul2"]
        if fel1["count"] == 0 and fel2["count"] == 0:
            continue  # meniu fără comenzi — nu apare
        lines.append(menu_name.upper())
        if fel1["count"] > 0:
            lines.append(f"  Felul 1: {fel1['text']} — {_portii(fel1['count'])}")
            total += fel1["count"]
        if fel2["count"] > 0:
            lines.append(f"  Felul 2: {fel2['text']} — {_portii(fel2['count'])}")
            total += fel2["count"]

    lines.append(SEPARATOR)
    lines.append(f"TOTAL PORȚII: {total}")
    lines += _person_lines(persons)

    return "\n".join(lines)


def build_andys_report(rows, report_date, office_address, persons=None):
    """
    Raportul text pentru Andy's.

    Args:
        rows: listă de dict-uri în forma „ANDY'S" documentată sus.
        report_date: str, ex. "2026-07-10"
        office_address: str
        persons: listă opțională pentru lista nominală (vezi docstring-ul modulului)

    Returns:
        str
    """
    counts = count_andys(rows)
    total = 0

    lines = [
        RESTAURANT_HEADERS["andys"],
        f"📅 {report_date}",
        f"📍 {office_address}",
        SEPARATOR,
    ]

    ordered = sorted(counts.keys(), key=lambda name: (counts[name]["sort_order"], name))
    for menu_name in ordered:
        entry = counts[menu_name]
        orders = entry["orders"]
        if orders == 0:
            continue  # business lunch fără comenzi — nu apare
        total += orders

        lines.append(f"{menu_name.upper()} — {_comenzi(orders)}")

        fel2 = entry["felul2"]
        if fel2["count"] > 0:
            lines.append(f"  Felul 2 (inclus): {fel2['text']} — {_portii(fel2['count'])}")

        visible_options = [o for o in entry["felul1_options"] if o["count"] > 0]
        if visible_options:
            lines.append("  Felul 1:")
            for opt in visible_options:
                lines.append(f"    {opt['text']} — {_portii(opt['count'])}")

    lines.append(SEPARATOR)
    lines.append(f"TOTAL COMENZI: {total}")
    lines += _person_lines(persons)

    return "\n".join(lines)


# Aliasuri: app.py importă funcțiile sub numele `generate_*`. Numele canonice
# (din contract) rămân `build_*`.
generate_sezatoare_report = build_sezatoare_report
generate_andys_report = build_andys_report
