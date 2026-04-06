"""
Portion calculation logic for the export/report feature.

Rules:
- "ambele" (Felul 1 + Felul 2) → counts as 1 Maxi portion
- "felul2" only → counts as 1 Standard portion
- "felul1" only → two such selections combine into 1 Maxi portion;
  if odd number, the remainder counts as 1 Standard portion

This is per menu: calculations are done separately for each menu name.
"""

from collections import defaultdict

FEL_LABELS_RO = {
    "felul1": "Felul 1",
    "felul2": "Felul 2",
    "ambele": "Felul 1 + Felul 2",
}

FEL_LABELS_RU = {
    "felul1": "Блюдо 1",
    "felul2": "Блюдо 2",
    "ambele": "Блюдо 1 + Блюдо 2",
}


def calculate_portions(selections):
    """
    Calculate portions from a list of selections.

    Args:
        selections: list of dicts with keys:
            - menu_name: str (e.g. "Lunch 1")
            - fel_selectat: str ("felul1", "felul2", "ambele")
            - sort_order: int (optional, for ordering)

    Returns:
        dict mapping menu_name -> {"maxi": int, "standard": int, "sort_order": int,
                                    "felul1_count": int, "felul2_count": int, "ambele_count": int}
    """
    grouped = defaultdict(lambda: {"ambele": 0, "felul1": 0, "felul2": 0, "sort_order": 0, "garnitura": ""})

    for sel in selections:
        menu_name = sel["menu_name"]
        fel = sel["fel_selectat"]
        if fel in ("ambele", "felul1", "felul2"):
            grouped[menu_name][fel] += 1
        if "sort_order" in sel:
            grouped[menu_name]["sort_order"] = sel["sort_order"]
        if sel.get("garnitura"):
            grouped[menu_name]["garnitura"] = sel["garnitura"]

    result = {}
    for menu_name, counts in grouped.items():
        maxi = counts["ambele"]
        standard = counts["felul2"]

        # Two "felul1 only" selections combine into 1 Maxi
        felul1_pairs = counts["felul1"] // 2
        felul1_remainder = counts["felul1"] % 2

        maxi += felul1_pairs
        standard += felul1_remainder

        result[menu_name] = {
            "maxi": maxi,
            "standard": standard,
            "sort_order": counts["sort_order"],
            "felul1_count": counts["felul1"],
            "felul2_count": counts["felul2"],
            "ambele_count": counts["ambele"],
            "garnitura": counts["garnitura"],
        }

    return result


def generate_report_text(selections, report_date, office_address, person_data=None):
    """
    Generate the text report for the admin export.

    Args:
        selections: list of dicts with menu_name, fel_selectat, sort_order
        report_date: date string (e.g. "2024-03-15")
        office_address: str
        person_data: list of dicts with name, menu_name, menu_name_ru, fel_selectat, sort_order

    Returns:
        str: formatted report text
    """
    portions = calculate_portions(selections)
    total = 0

    lines = [
        f"📅 {report_date}",
        f"📍 {office_address}",
        "━━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Sort by sort_order (Luch 1=0, Luch 2=1, Dieta=2, Post=3)
    sorted_menus = sorted(portions.keys(), key=lambda name: portions[name]["sort_order"])

    for menu_name in sorted_menus:
        p = portions[menu_name]
        if p["maxi"] > 0:
            lines.append(f"{menu_name.upper()} MAXI (Felul 1 + Felul 2) — {p['maxi']} porții")
            total += p["maxi"]
        if p["standard"] > 0:
            lines.append(f"{menu_name.upper()} STANDARD (doar Felul 2) — {p['standard']} porții")
            total += p["standard"]

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"TOTAL PORȚII: {total}")

    # Section: counts per menu
    lines.append("")
    lines.append("📊 DETALII COMENZI:")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    for menu_name in sorted_menus:
        p = portions[menu_name]
        total_menu = p["felul1_count"] + p["felul2_count"] + p["ambele_count"]
        garnitura_text = f" | Garnitură: {p['garnitura']}" if p.get("garnitura") else ""
        lines.append(f"{menu_name.upper()}: {total_menu} comenzi")
        lines.append(f"  Felul 1: {p['felul1_count']} | Felul 2: {p['felul2_count']} | Felul 1+2: {p['ambele_count']}{garnitura_text}")

    # Section: per person (RO)
    if person_data:
        lines.append("")
        lines.append("👤 COMENZI PER PERSOANĂ (RO):")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        sorted_persons = sorted(person_data, key=lambda p: p.get("sort_order", 0))
        for p in sorted_persons:
            fel_label = FEL_LABELS_RO.get(p["fel_selectat"], p["fel_selectat"])
            lines.append(f"  {p['name']} — {p['menu_name']} — {fel_label}")

        # Section: per person (RU)
        lines.append("")
        lines.append("👤 ЗАКАЗЫ ПО ПЕРСОНАМ (RU):")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
        for p in sorted_persons:
            fel_label = FEL_LABELS_RU.get(p["fel_selectat"], p["fel_selectat"])
            menu_ru = p.get("menu_name_ru") or p["menu_name"]
            lines.append(f"  {p['name']} — {menu_ru} — {fel_label}")

    return "\n".join(lines)
