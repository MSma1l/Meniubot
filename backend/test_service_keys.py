"""Teste pentru cheile de serviciu (`SERVICE_API_KEYS`, antetul `X-Service-Key`) și `/api/health`.

Refolosește mediul și BaseCase-ul din test_api (aceeași aplicație, aceeași bază temporară).
`SERVICE_API_KEYS` se citește la fiecare cerere (cu cache pe șir), deci fiecare test își
pune propriile chei în os.environ.

    python -m unittest test_service_keys -v
"""
import logging
import os
import unittest
from unittest import mock

import test_api as T  # noqa: E402 — setează mediul înainte de `import app`
import app as A
import auth
from auth import parse_service_keys, match_service_key, SlidingWindowLimiter, SERVICE_SCOPES
from models import db, BotControl

SECRET_READ = "r" * 64
SECRET_BOT = "b" * 40
SECRET_ALL = "a" * 32
SECRET_OTHER = "o" * 48  # are doar instructions:read — „nu are scope-ul" pentru restul

ALL = ",".join(sorted(SERVICE_SCOPES))
KEYS_ENV = ";".join([
    f"portal|{SECRET_READ}|menus:read,orders:read,users:read",
    f"ops|{SECRET_BOT}|bot:control",
    f"full|{SECRET_ALL}|{ALL}",
    f"other|{SECRET_OTHER}|instructions:read",
])

# Tabelul contractului: (metodă, regulă Flask) → scope. Ținut în pas cu docs/04-api.md.
EXPECTED_SCOPES = {
    ("GET", "/api/menus"): "menus:read",
    ("GET", "/api/menus/today"): "menus:read",
    ("POST", "/api/menus"): "menus:write",
    ("PUT", "/api/menus/<int:menu_id>"): "menus:write",
    ("DELETE", "/api/menus/<int:menu_id>"): "menus:write",
    ("POST", "/api/menus/<int:menu_id>/options"): "menus:write",
    ("PUT", "/api/menu-options/<int:option_id>"): "menus:write",
    ("DELETE", "/api/menu-options/<int:option_id>"): "menus:write",
    ("POST", "/api/menus/reset-content"): "menus:write",
    ("POST", "/api/menus/<int:menu_id>/approve"): "menus:write",
    ("POST", "/api/menus/approve-today"): "menus:write",
    ("GET", "/api/selections"): "orders:read",
    ("GET", "/api/orders/monthly"): "orders:read",
    ("GET", "/api/report"): "orders:read",
    ("GET", "/api/users"): "users:read",
    ("GET", "/api/users/<int:user_id>/history"): "users:read",
    ("PUT", "/api/users/<int:user_id>"): "users:write",
    ("DELETE", "/api/users/<int:user_id>"): "users:write",
    ("GET", "/api/budget-settings"): "budget:read",
    ("PUT", "/api/budget-settings"): "budget:write",
    ("POST", "/api/users/<int:user_id>/extra-budget"): "budget:write",
    ("GET", "/api/attendance"): "attendance:read",
    ("GET", "/api/attendance/stats"): "attendance:read",
    ("POST", "/api/attendance"): "attendance:write",
    ("POST", "/api/attendance/bulk"): "attendance:write",
    ("POST", "/api/ordering/open"): "ordering:write",
    ("POST", "/api/ordering/close"): "ordering:write",
    ("POST", "/api/notify/food-arrived"): "notify:send",
    ("POST", "/api/broadcast"): "notify:send",
    ("PUT", "/api/bot/settings"): "settings:write",
    ("GET", "/api/instructions/all"): "instructions:read",
    ("POST", "/api/instructions"): "instructions:write",
    ("PUT", "/api/instructions/<int:instr_id>"): "instructions:write",
    ("DELETE", "/api/instructions/<int:instr_id>"): "instructions:write",
    ("POST", "/api/instructions/<int:instr_id>/remove-image"): "instructions:write",
    ("POST", "/api/bot/stop"): "bot:control",
    ("POST", "/api/bot/start"): "bot:control",
}


def _concrete(rule):
    """Regula Flask cu parametrii înlocuiți de un id care nu există."""
    for name in ("menu_id", "option_id", "user_id", "instr_id"):
        rule = rule.replace(f"<int:{name}>", "999999")
    return rule


def admin_routes():
    """(metodă, regulă, view) pentru fiecare rută protejată de token_required."""
    out = []
    for rule in A.app.url_map.iter_rules():
        view = A.app.view_functions[rule.endpoint]
        if not getattr(view, "token_required", False):
            continue
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            out.append((method, rule.rule, view))
    return out


class ServiceKeyCase(T.BaseCase):

    def setUp(self):
        super().setUp()
        self._old_env = os.environ.get("SERVICE_API_KEYS")
        os.environ["SERVICE_API_KEYS"] = KEYS_ENV
        auth.service_key_limiter.reset()

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("SERVICE_API_KEYS", None)
        else:
            os.environ["SERVICE_API_KEYS"] = self._old_env
        auth.service_key_limiter.reset()
        super().tearDown()

    @staticmethod
    def key(secret):
        return {"X-Service-Key": secret}


# ══ Tabelul scope → rută ═════════════════════════════════════
class ScopeTableTest(ServiceKeyCase):

    def test_every_admin_route_declares_the_contract_scope(self):
        found = {(m, r): getattr(v, "required_scope", None) for m, r, v in admin_routes()}
        self.assertEqual(found, EXPECTED_SCOPES)

    def test_key_without_scope_gets_403_on_every_admin_route(self):
        for (method, rule), scope in EXPECTED_SCOPES.items():
            secret = SECRET_OTHER if scope != "instructions:read" else SECRET_BOT
            r = self.client.open(_concrete(rule), method=method, headers=self.key(secret),
                                 json={})
            self.assertEqual(r.status_code, 403, (method, rule))
            self.assertEqual(r.get_json(), {"error": "forbidden_scope", "scope": scope})

    def test_full_key_passes_the_gate_on_every_admin_route(self):
        # Doar rutele de citire — cele de scriere ar avea efecte; poarta e aceeași.
        for (method, rule), scope in EXPECTED_SCOPES.items():
            if method != "GET":
                continue
            path = _concrete(rule)
            if rule == "/api/report":
                path += "?restaurant=sezatoare"
            r = self.client.get(path, headers=self.key(SECRET_ALL))
            self.assertIn(r.status_code, (200, 404), (rule, r.get_json()))

    def test_jwt_still_passes_every_scope(self):
        for (method, rule), scope in EXPECTED_SCOPES.items():
            if method != "GET":
                continue
            path = _concrete(rule)
            if rule == "/api/report":
                path += "?restaurant=sezatoare"
            r = self.client.get(path, headers=self.auth)
            self.assertIn(r.status_code, (200, 404), rule)

    def test_jwt_write_routes_unchanged(self):
        r = self.client.put("/api/budget-settings", headers=self.auth,
                            json={"default_budget": 77})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/budget-settings", headers=self.auth)
                         .get_json()["default_budget"], 77)
        r = self.client.post("/api/ordering/close", headers=self.auth)
        self.assertEqual(r.status_code, 200)

    def test_require_scope_rejects_unknown_scope_at_definition(self):
        with self.assertRaises(ValueError):
            A.require_scope("menus:everything")

    def test_require_scope_without_token_required_fails_closed(self):
        view = A.require_scope("menus:read")(lambda: "secret")
        with A.app.test_request_context("/x"):
            resp, status = view()
        self.assertEqual(status, 401)


# ══ Autentificarea cu cheie ══════════════════════════════════
class ServiceKeyAuthTest(ServiceKeyCase):

    def test_valid_key_with_scope_200(self):
        r = self.client.get("/api/users", headers=self.key(SECRET_READ))
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.get_json(), list)
        r = self.client.get("/api/selections", headers=self.key(SECRET_READ))
        self.assertEqual(r.status_code, 200)

    def test_valid_key_without_scope_403(self):
        r = self.client.post("/api/ordering/close", headers=self.key(SECRET_READ))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json(), {"error": "forbidden_scope", "scope": "ordering:write"})
        # nu s-a executat nimic
        self.assertTrue(self.client.get("/api/ordering/status").get_json()["ordering_open"])

    def test_wrong_key_401(self):
        r = self.client.get("/api/users", headers=self.key("x" * 64))
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json(), {"error": "Invalid service key"})

    def test_empty_key_header_401(self):
        r = self.client.get("/api/users", headers=self.key(""))
        self.assertEqual(r.status_code, 401)

    def test_wrong_key_is_not_rescued_by_a_valid_jwt(self):
        # Antetul X-Service-Key decide: o cheie greșită e 401 chiar cu JWT bun alături.
        r = self.client.get("/api/users", headers={**self.auth, **self.key("x" * 64)})
        self.assertEqual(r.status_code, 401)

    def test_no_credentials_401(self):
        self.assertEqual(self.client.get("/api/users").status_code, 401)

    def test_feature_off_when_env_empty(self):
        os.environ["SERVICE_API_KEYS"] = ""
        r = self.client.get("/api/users", headers=self.key(SECRET_READ))
        self.assertEqual(r.status_code, 401)
        os.environ.pop("SERVICE_API_KEYS")
        r = self.client.get("/api/users", headers=self.key(SECRET_READ))
        self.assertEqual(r.status_code, 401)

    def test_constant_time_compare_against_every_secret(self):
        calls = []
        real = auth.hmac.compare_digest

        def spy(a, b):
            calls.append(b)
            return real(a, b)

        with mock.patch.object(auth.hmac, "compare_digest", side_effect=spy):
            # se potrivește cu PRIMA cheie, dar le compară pe toate
            self.assertEqual(match_service_key(SECRET_READ).key_id, "portal")
        self.assertEqual(sorted(calls), sorted(s.encode() for s in
                                               (SECRET_READ, SECRET_BOT, SECRET_ALL,
                                                SECRET_OTHER)))

    def test_match_returns_none_for_missing(self):
        self.assertIsNone(match_service_key(None))
        self.assertIsNone(match_service_key(""))


# ══ Bot stop/start ═══════════════════════════════════════════
class ServiceKeyBotControlTest(ServiceKeyCase):

    def test_bot_control_key_stops_and_starts_without_password(self):
        r = self.client.post("/api/bot/stop", headers=self.key(SECRET_BOT))
        self.assertEqual(r.status_code, 200)
        self.fresh()
        self.assertFalse(BotControl.query.get(1).is_enabled)
        r = self.client.post("/api/bot/start", headers=self.key(SECRET_BOT), json={})
        self.assertEqual(r.status_code, 200)
        self.fresh()
        self.assertTrue(BotControl.query.get(1).is_enabled)

    def test_key_without_bot_control_403_even_with_password(self):
        r = self.client.post("/api/bot/stop", headers=self.key(SECRET_READ),
                             json={"password": T.ADMIN_PASS})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["scope"], "bot:control")
        self.fresh()
        self.assertTrue(BotControl.query.get(1).is_enabled)

    def test_jwt_still_needs_password(self):
        self.assertEqual(self.client.post("/api/bot/stop", headers=self.auth).status_code, 401)
        self.assertEqual(self.client.post("/api/bot/stop", headers=self.auth,
                                          json={"password": T.ADMIN_PASS}).status_code, 200)


# ══ Health ═══════════════════════════════════════════════════
class HealthTest(ServiceKeyCase):

    def test_health_public(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json(), {"status": "ok"})


# ══ Limita de rată ═══════════════════════════════════════════
class RateLimitTest(ServiceKeyCase):

    def test_429_with_retry_after_when_window_full(self):
        with mock.patch.object(auth.service_key_limiter, "limit", 3):
            for _ in range(3):
                self.assertEqual(self.client.get("/api/users",
                                                 headers=self.key(SECRET_READ)).status_code, 200)
            r = self.client.get("/api/users", headers=self.key(SECRET_READ))
            self.assertEqual(r.status_code, 429)
            self.assertGreaterEqual(int(r.headers["Retry-After"]), 1)
            self.assertLessEqual(int(r.headers["Retry-After"]), 60)
            self.assertEqual(r.get_json()["error"], "rate_limited")
            # per key_id: altă cheie nu e afectată, și nici JWT-ul
            self.assertEqual(self.client.get("/api/users",
                                             headers=self.key(SECRET_ALL)).status_code, 200)
            self.assertEqual(self.client.get("/api/users", headers=self.auth).status_code, 200)

    def test_sliding_window_frees_up(self):
        now = [1000.0]
        lim = SlidingWindowLimiter(2, 60.0, clock=lambda: now[0])
        self.assertEqual(lim.hit("k"), 0)
        now[0] += 30
        self.assertEqual(lim.hit("k"), 0)
        self.assertEqual(lim.hit("k"), 30)  # cea mai veche iese peste 30s
        now[0] += 30
        self.assertEqual(lim.hit("k"), 0)
        self.assertEqual(lim.hit("other"), 0)


# ══ Parsarea mediului ════════════════════════════════════════
class ParseServiceKeysTest(unittest.TestCase):

    def test_valid_entries(self):
        keys = parse_service_keys(f" portal|{SECRET_READ}|menus:read, orders:read ;"
                                  f"ops|{SECRET_BOT}|bot:control;")
        self.assertEqual([k.key_id for k in keys], ["portal", "ops"])
        self.assertEqual(keys[0].scopes, {"menus:read", "orders:read"})

    def test_empty_means_off(self):
        self.assertEqual(parse_service_keys(""), ())
        self.assertEqual(parse_service_keys(None), ())
        self.assertEqual(parse_service_keys(" ; ;"), ())

    def test_malformed_entries_ignored_with_warning_and_no_secret(self):
        short = "s" * 31
        long_ = "L" * 64
        raw = ";".join([
            f"short|{short}|menus:read",                 # secret prea scurt
            f"{long_}|menus:read",                        # 2 părți
            f"bad id|{long_}|menus:read",                 # key_id invalid
            f"noscope|{long_}|",                          # niciun scope
            f"typo|{long_}|menus:reed",                   # doar scope necunoscut
            f"ok|{long_}|menus:read,users:fly",           # unul bun, unul necunoscut
            f"ok|{'d' * 40}|menus:read",                  # key_id duplicat
            f"dup|{long_}|menus:read",                    # secret duplicat
        ])
        with self.assertLogs("auth", level="WARNING") as cm:
            keys = parse_service_keys(raw)
        self.assertEqual([(k.key_id, k.scopes) for k in keys], [("ok", {"menus:read"})])
        out = "\n".join(cm.output)
        self.assertEqual(len(cm.records), 9)  # 7 intrări respinse + 2 avertismente de scope necunoscut
        self.assertNotIn(short, out)
        self.assertNotIn(long_, out)
        self.assertNotIn("d" * 40, out)

    def test_repr_hides_secret(self):
        key = parse_service_keys(f"portal|{SECRET_READ}|menus:read")[0]
        self.assertNotIn(SECRET_READ, repr(key))
        self.assertNotIn(SECRET_READ, str(key))


# ══ Logurile nu conțin secretul ══════════════════════════════
class AuditLogTest(ServiceKeyCase):

    def test_audit_line_has_key_id_method_path_status_and_never_the_secret(self):
        with self.assertLogs("app", level="INFO") as cm:
            self.client.get("/api/users", headers=self.key(SECRET_READ))
            self.client.post("/api/ordering/close", headers=self.key(SECRET_READ))
            self.client.get("/api/users", headers=self.key("z" * 64))
        out = "\n".join(cm.output)
        self.assertIn("key_id=portal method=GET path=/api/users status=200", out)
        self.assertIn("key_id=portal method=POST path=/api/ordering/close status=403", out)
        self.assertIn("Cheie de serviciu invalidă", out)
        for secret in (SECRET_READ, "z" * 64):
            self.assertNotIn(secret, out)

    def test_no_secret_anywhere_in_logs(self):
        # Prinde tot ce se loghează (orice logger, orice nivel) pe o cerere completă,
        # inclusiv recitirea mediului cu o cheie nouă și o intrare malformată.
        os.environ["SERVICE_API_KEYS"] = KEYS_ENV + f";broken|{'q' * 20}|menus:read"
        with self.assertLogs(level="DEBUG") as cm:
            self.client.get("/api/users", headers=self.key(SECRET_READ))
            self.client.post("/api/bot/stop", headers=self.key(SECRET_BOT))
            self.client.get("/api/users", headers=self.key("y" * 64))
        out = "\n".join(cm.output)
        for secret in (SECRET_READ, SECRET_BOT, SECRET_ALL, SECRET_OTHER, "q" * 20, "y" * 64):
            self.assertNotIn(secret, out)

    def test_jwt_requests_are_not_audited_as_service(self):
        with self.assertLogs("app", level="INFO") as cm:
            self.client.get("/api/users", headers=self.auth)
            logging.getLogger("app").info("marker")
        self.assertFalse(any("service-key" in line for line in cm.output))


if __name__ == "__main__":
    unittest.main()
