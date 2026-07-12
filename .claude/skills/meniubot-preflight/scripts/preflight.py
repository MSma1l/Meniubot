#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
preflight.py — checklist automat înainte de deploy MeniuBot.

Rulează un set de verificări BLOCANTE și de AVERTISMENT peste repo-ul MeniuBot
și spune exact ce trebuie reparat înainte de a pune aplicația în producție.

Utilizare:
    python3 preflight.py [--root .] [--env .env]

Cod de ieșire:
    0 — nu există eșecuri BLOCANTE (avertismentele NU blochează)
    1 — există cel puțin un eșec BLOCANT

Fără dependențe externe: doar stdlib (pathlib, re, ast, argparse, os, sys).
"""

import argparse
import ast
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Culori simple (dezactivate automat dacă ieșirea nu e un terminal)
# ---------------------------------------------------------------------------
_USE_COLOR = sys.stdout.isatty() and os.getenv("NO_COLOR") is None


def _c(code, text):
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def red(t):
    return _c("31", t)


def yellow(t):
    return _c("33", t)


def green(t):
    return _c("32", t)


def bold(t):
    return _c("1", t)


# ---------------------------------------------------------------------------
# Colector de rezultate
# ---------------------------------------------------------------------------
class Report:
    def __init__(self):
        self.blockers = 0
        self.warnings = 0

    def fail(self, msg):
        """Eșec BLOCANT — oprește deploy-ul."""
        self.blockers += 1
        print(f"  {red('✗')} {red('BLOCANT')}  {msg}")

    def warn(self, msg):
        """Avertisment — nu blochează, dar merită atenție."""
        self.warnings += 1
        print(f"  {yellow('!')} {yellow('ATENȚIE')}  {msg}")

    def ok(self, msg):
        print(f"  {green('✓')} {msg}")

    def info(self, msg):
        print(f"    {msg}")


# ---------------------------------------------------------------------------
# Utilitare
# ---------------------------------------------------------------------------
def parse_env(env_path: Path):
    """Parsează un fișier .env simplu în dict. Ignoră comentariile și liniile goale."""
    data = {}
    if not env_path.exists():
        return data
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        # elimină ghilimelele înconjurătoare, dacă există
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        data[key] = val
    return data


def read_text(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# Lista de referință: cele 8 rute publice cunoscute și ACCEPTATE azi.
# După închiderea găurilor P0, selecțiile, înregistrarea, verificarea userului,
# pending-users și bot/stop|start au căpătat autentificare. Ce rămâne public e
# strict ce trebuie să fie: login-ul, statusuri de citit și fișiere servite.
KNOWN_PUBLIC = {
    "login",
    "get_approved_menus_today",
    "bot_status",
    "ordering_status",
    "serve_webapp",
    "webapp_ordering_status",
    "serve_upload",
    "get_instructions",
}

# Decoratorii care fac o rută PROTEJATĂ. O rută e publică doar dacă nu are niciunul.
#   token_required                 → JWT admin
#   require_telegram               → initData Telegram semnat
#   require_internal               → X-Internal-Token (procesul bot)
#   require_telegram_or_internal   → oricare din cele două de mai sus
PROTECTING_DECORATORS = {
    "token_required",
    "require_telegram",
    "require_internal",
    "require_telegram_or_internal",
}


def _decorator_names(func: ast.FunctionDef):
    """Întoarce (has_route, is_protected) pentru o funcție dată.

    is_protected = True dacă funcția poartă cel puțin unul dintre decoratorii de
    autentificare din PROTECTING_DECORATORS.
    """
    has_route = False
    is_protected = False
    for dec in func.decorator_list:
        # @app.route(...) -> Call cu func Attribute(app.route)
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Attribute) and target.attr == "route":
            if isinstance(target.value, ast.Name) and target.value.id == "app":
                has_route = True
        # @token_required / @require_telegram / ... -> Name simplu
        if isinstance(target, ast.Name) and target.id in PROTECTING_DECORATORS:
            is_protected = True
    return has_route, is_protected


def analyze_routes(source: str):
    """
    Parsează backend/app.py cu ast și întoarce (all_routes, public_routes).

    all_routes    = listă cu numele funcțiilor decorate cu @app.route
    public_routes = subsetul fără niciun decorator de autentificare
    """
    tree = ast.parse(source)
    all_routes = []
    public_routes = []
    for node in tree.body:  # doar nivelul de modul
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            has_route, is_protected = _decorator_names(node)
            if has_route:
                all_routes.append(node.name)
                if not is_protected:
                    public_routes.append(node.name)
    return all_routes, public_routes


# ---------------------------------------------------------------------------
# Verificări
# ---------------------------------------------------------------------------
def check_env_file(rep, env_path: Path):
    print(bold("\n[1] Fișierul .env"))
    if not env_path.exists():
        rep.fail(
            f".env lipsește la '{env_path}'. Rulează: cp .env.example .env "
            "și completează valorile reale."
        )
        return None
    rep.ok(f".env găsit la {env_path}")
    return parse_env(env_path)


def check_secret_key(rep, env):
    print(bold("\n[2] SECRET_KEY"))
    if env is None:
        rep.info("Sărit — .env lipsește.")
        return
    val = env.get("SECRET_KEY")
    # app.py respinge explicit exact aceste valori și ridică RuntimeError la pornire.
    bad_defaults = {"your_secret_key", "dev-secret-key"}
    gen = 'python3 -c "import secrets; print(secrets.token_hex(32))"'
    if not val:
        rep.fail(
            f"SECRET_KEY lipsește sau e gol. app.py ridică RuntimeError și aplicația "
            f"NU pornește fără el. Generează unul: {gen}"
        )
    elif val in bad_defaults:
        rep.fail(
            f"SECRET_KEY are valoarea implicită publică '{val}'. app.py respinge "
            f"explicit 'dev-secret-key' și 'your_secret_key' și NU pornește cu ele "
            f"(permit forjarea de JWT de admin). Generează unul real: {gen}"
        )
    elif len(val) < 32:
        rep.fail(
            f"SECRET_KEY are doar {len(val)} caractere (minim 32). "
            f"Generează unul mai lung: {gen}"
        )
    else:
        rep.ok(f"SECRET_KEY setat, {len(val)} caractere, nu e un default cunoscut.")


def check_internal_token(rep, env):
    print(bold("\n[2b] INTERNAL_API_TOKEN"))
    if env is None:
        rep.info("Sărit — .env lipsește.")
        return
    val = env.get("INTERNAL_API_TOKEN")
    gen = 'python3 -c "import secrets; print(secrets.token_hex(32))"'
    if not val:
        rep.fail(
            f"INTERNAL_API_TOKEN lipsește sau e gol. E secretul cu care procesul bot "
            f"se autentifică la API-ul intern (register, pending-users). app.py ridică "
            f"RuntimeError și aplicația NU pornește fără el. Generează unul: {gen}"
        )
    elif val == "test-internal-token":
        rep.fail(
            "INTERNAL_API_TOKEN are valoarea de test 'test-internal-token' "
            f"(folosită de smoke test). Pune un secret real: {gen}"
        )
    elif len(val) < 32:
        rep.fail(
            f"INTERNAL_API_TOKEN are doar {len(val)} caractere (minim 32). "
            f"Generează unul mai lung: {gen}"
        )
    else:
        rep.ok(f"INTERNAL_API_TOKEN setat, {len(val)} caractere, nu e valoarea de test.")


def check_admin_password(rep, env):
    print(bold("\n[3] ADMIN_PASSWORD"))
    if env is None:
        rep.info("Sărit — .env lipsește.")
        return
    val = env.get("ADMIN_PASSWORD")
    if not val:
        rep.fail("ADMIN_PASSWORD lipsește sau e gol. Setează o parolă puternică.")
    elif val == "admin":
        rep.fail(
            "ADMIN_PASSWORD este 'admin' — parola implicită. "
            "Schimb-o cu o parolă puternică în .env."
        )
    else:
        rep.ok("ADMIN_PASSWORD setat și diferit de 'admin'.")


def check_bot_token(rep, env):
    print(bold("\n[4] TELEGRAM_BOT_TOKEN"))
    if env is None:
        rep.info("Sărit — .env lipsește.")
        return
    val = env.get("TELEGRAM_BOT_TOKEN")
    if not val:
        rep.fail(
            "TELEGRAM_BOT_TOKEN lipsește sau e gol. "
            "Ia un token de la @BotFather și pune-l în .env."
        )
    elif val == "your_token_here":
        rep.fail(
            "TELEGRAM_BOT_TOKEN are placeholder-ul 'your_token_here'. "
            "Înlocuiește-l cu tokenul real de la @BotFather."
        )
    else:
        rep.ok("TELEGRAM_BOT_TOKEN setat.")


def check_webapp_url(rep, env):
    print(bold("\n[5] WEBAPP_URL"))
    if env is None:
        rep.info("Sărit — .env lipsește.")
        return
    val = env.get("WEBAPP_URL")
    if not val:
        rep.fail(
            "WEBAPP_URL lipsește sau e gol. "
            "Telegram acceptă WebApp doar pe https://<domeniul-tău>/webapp."
        )
        return
    if not val.startswith("https://"):
        rep.fail(
            f"WEBAPP_URL='{val}' nu începe cu https://. "
            "Telegram refuză WebApp pe http. Folosește un URL https."
        )
    elif "yourdomain.com" in val:
        rep.fail(
            f"WEBAPP_URL='{val}' conține placeholder-ul 'yourdomain.com'. "
            "Pune domeniul real."
        )
    else:
        rep.ok(f"WEBAPP_URL={val}")


def check_debug(rep, app_source, app_path):
    print(bold("\n[6] Flask debug în backend/app.py"))
    if app_source is None:
        rep.fail(f"Nu pot citi {app_path}.")
        return
    if re.search(r"debug\s*=\s*True", app_source):
        rep.fail(
            f"{app_path} conține debug=True (în blocul if __name__ == \"__main__\"). "
            "Scoate debug=True înainte de deploy — expune debugger-ul Werkzeug "
            "și permite execuție de cod la distanță."
        )
    else:
        rep.ok("app.py nu conține debug=True.")


def check_routes(rep, app_source, app_path):
    print(bold("\n[7] Rute Flask publice"))
    if app_source is None:
        rep.warn(f"Nu pot citi {app_path} pentru analiza rutelor.")
        return
    try:
        all_routes, public_routes = analyze_routes(app_source)
    except SyntaxError as exc:
        rep.warn(f"Nu pot parsa {app_path} cu ast: {exc}")
        return

    rep.info(
        f"Rute @app.route găsite: {len(all_routes)} | publice (fără decorator de "
        f"autentificare): {len(public_routes)}"
    )
    public_set = set(public_routes)
    new_public = sorted(public_set - KNOWN_PUBLIC)
    missing = sorted(KNOWN_PUBLIC - public_set)

    if new_public:
        for name in new_public:
            rep.fail(
                f"endpoint public nou: {name}; confirmă intenționat "
                "sau adaugă @token_required sub @app.route."
            )
    if missing:
        rep.warn(
            "Rute din lista de referință care NU mai sunt publice (verifică dacă e "
            f"intenționat): {', '.join(missing)}"
        )
    if not new_public and not missing:
        rep.ok(
            f"Lista publică neschimbată ({len(public_set)} rute, toate în lista de "
            "referință acceptată)."
        )
        rep.warn(
            "Reamintire — găurile P0 sunt închise (selecțiile cer initData semnat, "
            "register/pending-users cer X-Internal-Token, bot/stop|start cer JWT admin). "
            "Ce rămâne deschis: NU există rate limiting pe POST /api/auth/login (P1.5) — "
            "login-ul e vulnerabil la brute-force — și CORS-ul e complet deschis, "
            "CORS(app) fără origini restrânse (P1.4). Vezi docs/09-probleme-cunoscute.md."
        )


def check_frontend_dockerfile(rep, root: Path):
    print(bold("\n[8] frontend/Dockerfile"))
    path = root / "frontend" / "Dockerfile"
    src = read_text(path)
    if src is None:
        rep.info(f"Sărit — {path} lipsește.")
        return
    # Prinde atât forma shell ("npm run dev") cât și forma JSON-array
    # ("npm", "run", "dev") folosită în CMD/ENTRYPOINT.
    runs_dev = bool(
        re.search(r"npm\s+run\s+dev", src)
        or re.search(r'"npm"\s*,\s*"run"\s*,\s*"dev"', src)
    )
    if runs_dev:
        rep.warn(
            "frontend/Dockerfile rulează 'npm run dev' — serverul de dezvoltare Vite "
            "în producție. Folosește build multi-stage (npm run build) + nginx. "
            "Vezi docs/09-probleme-cunoscute.md (P3.1) și docs/08-operare.md."
        )
    else:
        rep.ok("frontend/Dockerfile nu rulează 'npm run dev'.")


def _extract_allowed_hosts(vite_source):
    """Extrage lista allowedHosts din vite.config.ts (parsare textuală simplă)."""
    m = re.search(r"allowedHosts\s*:\s*\[([^\]]*)\]", vite_source)
    if not m:
        return None
    inner = m.group(1)
    return re.findall(r"['\"]([^'\"]+)['\"]", inner)


def _host_from_url(url):
    if not url:
        return None
    m = re.match(r"https?://([^/:]+)", url)
    return m.group(1) if m else None


def check_vite_hosts(rep, root: Path, env):
    print(bold("\n[9] frontend/vite.config.ts allowedHosts"))
    path = root / "frontend" / "vite.config.ts"
    src = read_text(path)
    if src is None:
        rep.info(f"Sărit — {path} lipsește.")
        return
    hosts = _extract_allowed_hosts(src)
    if hosts is None:
        rep.warn("Nu am găsit 'allowedHosts' în vite.config.ts.")
        return
    rep.info(f"allowedHosts = {hosts}")
    webapp_url = env.get("WEBAPP_URL") if env else None
    host = _host_from_url(webapp_url)
    if not host:
        rep.info("Nu pot deduce host-ul din WEBAPP_URL — sar peste comparație.")
        return
    if host not in hosts:
        rep.warn(
            f"Host-ul '{host}' din WEBAPP_URL nu e în allowedHosts {hosts}. "
            "Vite va bloca cererile de pe acel domeniu; adaugă-l în allowedHosts."
        )
    else:
        rep.ok(f"Host-ul '{host}' din WEBAPP_URL e în allowedHosts.")


def check_gunicorn(rep, root: Path):
    print(bold("\n[10] gunicorn vs backend/Dockerfile"))
    req = read_text(root / "backend" / "requirements.txt")
    dockerfile = read_text(root / "backend" / "Dockerfile")
    if req is None or dockerfile is None:
        rep.info("Sărit — requirements.txt sau backend/Dockerfile lipsește.")
        return
    has_gunicorn = "gunicorn" in req
    uses_python_run = re.search(r'CMD\s*\[\s*"python"\s*,\s*"run\.py"\s*\]', dockerfile)
    if has_gunicorn and uses_python_run:
        rep.warn(
            "gunicorn e în requirements.txt dar backend/Dockerfile rulează "
            'CMD ["python", "run.py"] (serverul de dezvoltare Flask). '
            "gunicorn e instalat dar nefolosit. NU trece la gunicorn înainte de a "
            "scoate db.create_all()/migrațiile de la nivel de modul din app.py "
            "(altfel rulează în fiecare worker). Vezi docs/09 (P3.2)."
        )
    elif has_gunicorn:
        rep.ok("gunicorn prezent și Dockerfile nu mai folosește python run.py.")
    else:
        rep.ok("gunicorn nu e în requirements.txt.")


def check_healthcheck(rep, root: Path):
    print(bold("\n[11] docker-compose.yml healthcheck"))
    src = read_text(root / "docker-compose.yml")
    if src is None:
        rep.info("Sărit — docker-compose.yml lipsește.")
        return
    if "healthcheck" not in src:
        rep.warn(
            "docker-compose.yml nu are niciun healthcheck. Adaugă un healthcheck pe "
            "backend ca Docker să repornească containerul când API-ul nu răspunde."
        )
    else:
        rep.ok("docker-compose.yml conține cel puțin un healthcheck.")


def check_gitignore_env(rep, root: Path):
    print(bold("\n[12] .env în .gitignore"))
    gi = read_text(root / ".gitignore")
    if gi is None:
        rep.fail(
            ".gitignore lipsește, deci .env poate ajunge în git cu toate secretele. "
            "Creează .gitignore și adaugă linia: .env"
        )
        return
    lines = {ln.strip() for ln in gi.splitlines()}
    if ".env" in lines:
        rep.ok(".env este ignorat de git (.gitignore conține '.env').")
    else:
        rep.fail(
            ".gitignore NU conține '.env'. Riscul e să comiți secretele. "
            "Adaugă linia: .env"
        )


def check_tests(rep, root: Path):
    print(bold("\n[13] Teste"))
    rep.info(
        "Comanda corectă de rulare a testelor: "
        "cd backend && python -m unittest test_calculations test_auth -v"
    )
    rep.info(
        "Fluxul zilnic (două restaurante) nu e acoperit de unittest — rulează și "
        "smoke-ul: python .claude/skills/meniubot-verify/scripts/smoke.py --in-process"
    )
    req = read_text(root / "backend" / "requirements.txt")
    readme = read_text(root / "README.md")
    pytest_in_req = bool(req) and "pytest" in req
    # Doar o COMANDĂ de rulare contează, nu simpla mențiune a cuvântului „pytest"
    # (README-ul explică tocmai că pytest NU e instalat — asta nu e o recomandare).
    pytest_cmd = bool(readme) and re.search(
        r"(python\s+-m\s+pytest|^\s*\$?\s*pytest\s+\S)", readme, re.M
    )
    if not pytest_in_req and pytest_cmd:
        rep.warn(
            "README recomandă o comandă 'pytest ...' dar pytest NU e în "
            "backend/requirements.txt. Folosește unittest (comanda de mai sus) sau "
            "adaugă pytest în requirements.txt."
        )
    elif not pytest_in_req:
        rep.ok("pytest nu e în requirements.txt; README folosește corect unittest.")
    else:
        rep.ok("pytest e în requirements.txt.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Checklist automat înainte de deploy MeniuBot."
    )
    parser.add_argument(
        "--root", default=".", help="Rădăcina repo-ului MeniuBot (implicit: .)"
    )
    parser.add_argument(
        "--env",
        default=None,
        help="Calea către fișierul .env (implicit: <root>/.env)",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    env_path = Path(args.env).resolve() if args.env else (root / ".env")
    app_path = root / "backend" / "app.py"
    app_source = read_text(app_path)

    print(bold(f"MeniuBot preflight — root: {root}"))

    rep = Report()

    env = check_env_file(rep, env_path)
    check_secret_key(rep, env)
    check_internal_token(rep, env)
    check_admin_password(rep, env)
    check_bot_token(rep, env)
    check_webapp_url(rep, env)
    check_debug(rep, app_source, app_path)
    check_routes(rep, app_source, app_path)
    check_frontend_dockerfile(rep, root)
    check_vite_hosts(rep, root, env)
    check_gunicorn(rep, root)
    check_healthcheck(rep, root)
    check_gitignore_env(rep, root)
    check_tests(rep, root)

    print(bold("\n" + "=" * 60))
    summary = f"{rep.blockers} blocante, {rep.warnings} avertismente"
    if rep.blockers:
        print(red(bold(f"REZULTAT: {summary}")))
        print(red("Deploy-ul NU e sigur — repară blocantele de mai sus."))
    else:
        print(green(bold(f"REZULTAT: {summary}")))
        print(green("Fără blocante — poți continua deploy-ul."))
    print(bold("=" * 60))

    return 1 if rep.blockers else 0


if __name__ == "__main__":
    sys.exit(main())
