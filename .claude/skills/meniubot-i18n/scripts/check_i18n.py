#!/usr/bin/env python3
"""Verifică simetria RO/RU în toate locurile unde MeniuBot ține texte.

Textele trăiesc în patru fișiere, fără bibliotecă de i18n. Scriptul le parsează
pe toate și raportează cheile care există într-o limbă dar nu în cealaltă,
plus textele hardcodate care ocolesc dicționarele.

    python check_i18n.py [--root .]

Iese cu 0 dacă totul e simetric, 1 dacă lipsesc chei.
"""
import argparse
import ast
import re
import sys
from pathlib import Path

# dicționare Python de forma {"ro": {...}, "ru": {...}}
PY_TARGETS = {
    "backend/bot.py": ["TEXTS"],
    "backend/app.py": [
        "FOOD_ARRIVED_TEXTS",
        "SELECTION_CONFIRM_TEXTS",
        "SELECTION_NO_LUNCH_TEXTS",
        "ORDERING_CLOSED_TEXTS",
        "FEL_LABELS",
    ],
}

# tipare de text bilingv scris direct în cod, în afara dicționarelor
HARDCODED = [
    ("backend/bot.py", r'if lang == "ru"', "ternar/if de limbă în loc de cheie în TEXTS"),
    ("backend/app.py", r'if lang == "ru" else', "etichetă construită inline"),
    ("backend/static/webapp/index.html", r"currentLang === 'ru' \?", "ternar de limbă în JS"),
]

problems = 0
warnings = 0


def problem(msg):
    global problems
    problems += 1
    print(f"  \033[31m✗\033[0m {msg}")


def warn(msg):
    global warnings
    warnings += 1
    print(f"  \033[33m!\033[0m {msg}")


def ok(msg):
    print(f"  \033[32m✓\033[0m {msg}")


def strip_js_strings(s: str) -> str:
    """Golește conținutul literalelor, ca să nu confundăm `'Alegerea ta: x'` cu o cheie."""
    s = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", s)
    s = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', s)
    return s


def dict_keys_from_py(path: Path, varname: str):
    """Întoarce {'ro': {chei}|None, 'ru': …} pentru o atribuire la nivel de modul.

    Valoarea e `None` când dicționarul e plat — adică un singur text per limbă,
    ca în FOOD_ARRIVED_TEXTS = {"ro": "…", "ru": "…"}.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == varname for t in node.targets):
            continue
        if not isinstance(node.value, ast.Dict):
            return None
        out = {}
        for k, v in zip(node.value.keys, node.value.values):
            if not isinstance(k, ast.Constant):
                continue
            if isinstance(v, ast.Dict):
                out[k.value] = {kk.value for kk in v.keys if isinstance(kk, ast.Constant)}
            else:
                out[k.value] = None
        return out
    return None


def js_texts_keys(path: Path):
    """Extrage cheile din `const TEXTS = { ro: {...}, ru: {...} }` din Mini App."""
    src = path.read_text(encoding="utf-8")
    m = re.search(r"const TEXTS = \{(.*?)\n  \};", src, re.S)
    if not m:
        return None
    body = strip_js_strings(m.group(1))
    out = {}
    for lang in ("ro", "ru"):
        lm = re.search(rf"\n    {lang}: \{{(.*?)\n    \}}", body, re.S)
        if not lm:
            continue
        # o cheie e `nume:` fie la început de linie, fie după o virgulă
        out[lang] = set(re.findall(r"(?:^\s+|,\s*)(\w+):", lm.group(1), re.M))
    return out or None


def compare(label, langs):
    if langs is None:
        problem(f"{label}: nu am putut parsa dicționarul")
        return

    present = set(langs)
    missing_lang = {"ro", "ru"} - present
    if missing_lang:
        problem(f"{label}: lipsește limba {'/'.join(sorted(missing_lang))}")
        return

    # dicționar plat: un text per limbă, nu chei
    if all(v is None for v in langs.values()):
        ok(f"{label}: text per limbă, ro+ru prezente")
        return

    ro, ru = langs.get("ro") or set(), langs.get("ru") or set()
    missing_ru, missing_ro = ro - ru, ru - ro
    if not missing_ru and not missing_ro:
        ok(f"{label}: {len(ro)} chei, simetric")
        return
    for k in sorted(missing_ru):
        problem(f"{label}: cheia '{k}' există în ro, lipsește în ru")
    for k in sorted(missing_ro):
        problem(f"{label}: cheia '{k}' există în ru, lipsește în ro")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root).resolve()

    print("\nSimetrie RO/RU\n")

    print("Dicționare Python")
    for rel, names in PY_TARGETS.items():
        path = root / rel
        if not path.exists():
            problem(f"{rel}: lipsește")
            continue
        for name in names:
            compare(f"{rel} :: {name}", dict_keys_from_py(path, name))

    print("\nMini App")
    webapp = root / "backend/static/webapp/index.html"
    if webapp.exists():
        compare("static/webapp/index.html :: TEXTS", js_texts_keys(webapp))
    else:
        problem("backend/static/webapp/index.html: lipsește")

    print("\nRaport")
    calc = root / "backend/calculations.py"
    if calc.exists():
        # aici cheile sunt felurile, iar limba e în numele variabilei
        src = calc.read_text(encoding="utf-8")
        keys_ro = set(dict_keys_from_py(calc, "FEL_LABELS_RO") or {})
        keys_ru = set(dict_keys_from_py(calc, "FEL_LABELS_RU") or {})
        if keys_ro == keys_ru and keys_ro:
            ok(f"calculations.py :: FEL_LABELS_RO/RU: {len(keys_ro)} chei, simetric")
        else:
            problem(f"calculations.py: FEL_LABELS_RO={sorted(keys_ro)} vs FEL_LABELS_RU={sorted(keys_ru)}")
        if "TOTAL PORȚII" in src:
            warn("calculations.py: antetele raportului sunt hardcodate în română (TOTAL PORȚII, DETALII COMENZI…)")

    print("\nTexte în afara dicționarelor")
    for rel, pattern, desc in HARDCODED:
        path = root / rel
        if not path.exists():
            continue
        hits = len(re.findall(pattern, path.read_text(encoding="utf-8")))
        if hits:
            warn(f"{rel}: {hits}× {desc}")

    print("\nGhiduri duplicate")
    bot = root / "backend/bot.py"
    if bot.exists() and re.search(r'Program comenzi|Время заказов', bot.read_text(encoding="utf-8")):
        warn("bot.py: ghidul are ore hardcodate, dar fereastra e configurabilă din Dashboard "
             "(BotControl.reminder_start/end)")
        warn("bot.py: TEXTS['guide'] duplică tabela `instructions` — nimic nu le sincronizează")

    print(f"\n{'─' * 52}")
    print(f"  {problems} probleme, {warnings} avertismente")
    print(f"{'─' * 52}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
