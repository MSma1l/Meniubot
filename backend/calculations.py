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


def calculate_portions(selections):
    """
    Calculate portions from a list of selections.

    Args:
        selections: list of dicts with keys:
            - menu_name: str (e.g. "Lunch 1")
            - fel_selectat: str ("felul1", "felul2", "ambele")

    Returns:
        dict mapping menu_name -> {"maxi": int, "standard": int}
    """
    grouped = defaultdict(lambda: {"ambele": 0, "felul1": 0, "felul2": 0})

    for sel in selections:
        menu_name = sel["menu_name"]
        fel = sel["fel_selectat"]
        if fel in grouped[menu_name]:
            grouped[menu_name][fel] += 1

    result = {}
    for menu_name, counts in grouped.items():
        maxi = counts["ambele"]
        standard = counts["felul2"]

        # Two "felul1 only" selections combine into 1 Maxi
        felul1_pairs = counts["felul1"] // 2
        felul1_remainder = counts["felul1"] % 2

        maxi += felul1_pairs
        standard += felul1_remainder

        result[menu_name] = {"maxi": maxi, "standard": standard}

    return result


def generate_report_text(selections, report_date, office_address):
    """
    Generate the text report for the admin export.

    Args:
        selections: list of dicts with menu_name and fel_selectat
        report_date: date string (e.g. "2024-03-15")
        office_address: str

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

    for menu_name in sorted(portions.keys()):
        p = portions[menu_name]
        if p["maxi"] > 0:
            lines.append(f"{menu_name.upper()} MAXI (Felul 1 + Felul 2) — {p['maxi']} porții")
            total += p["maxi"]
        if p["standard"] > 0:
            lines.append(f"{menu_name.upper()} STANDARD (doar Felul 2) — {p['standard']} porții")
            total += p["standard"]

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"TOTAL PORȚII: {total}")

    return "\n".join(lines)
