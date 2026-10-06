from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from securityguard.models import LoginAttemptBucket
from securityguard.middleware import bucket_key
from securityguard.production import configuration_errors


class LoginProtectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("owner", "owner@example.com", "Long-test-password-129!")

    def attempt(self, username="owner", password="wrong", path="/app/login/reception/", **extra):
        return self.client.post(path, {"username": username, "password": password}, **extra)

    def test_attempt_limit_shared_across_workspaces_and_admin(self):
        paths = ["/app/login/reception/", "/app/login/doctor/", "/app/login/patient/", "/admin/login/", "/app/login/reception/"]
        for path in paths:
            self.assertNotEqual(self.attempt(path=path).status_code, 429)
        with patch("django.contrib.auth.forms.authenticate") as authenticate:
            response = self.attempt()
        self.assertEqual(response.status_code, 429)
        self.assertGreater(int(response["Retry-After"]), 0)
        authenticate.assert_not_called()

    def test_expired_bucket_allows_retry(self):
        for _ in range(5):
            self.attempt()
        LoginAttemptBucket.objects.update(started_at=timezone.now() - timedelta(minutes=16))
        self.assertNotEqual(self.attempt().status_code, 429)

    def test_success_resets_account_not_address(self):
        self.attempt()
        response = self.attempt(password="Long-test-password-129!")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(LoginAttemptBucket.objects.filter(key=bucket_key("account", "owner")).exists())
        self.assertEqual(LoginAttemptBucket.objects.get(key=bucket_key("address", "127.0.0.1")).attempts, 2)

    @override_settings(LOGIN_ADDRESS_LIMIT=2)
    def test_forwarded_address_cannot_bypass_address_limit(self):
        self.attempt(username="one", HTTP_X_FORWARDED_FOR="1.1.1.1")
        self.attempt(username="two", HTTP_X_FORWARDED_FOR="2.2.2.2")
        self.assertEqual(self.attempt(username="three", HTTP_X_FORWARDED_FOR="3.3.3.3").status_code, 429)

    def test_buckets_do_not_store_identifiers(self):
        self.attempt()
        self.assertTrue(all(len(key) == 64 and "owner" not in key for key in LoginAttemptBucket.objects.values_list("key", flat=True)))

    def test_authenticated_user_cannot_clear_another_account_bucket(self):
        self.client.force_login(self.user)
        key = bucket_key("account", "victim")
        self.attempt(username="victim")
        self.assertTrue(LoginAttemptBucket.objects.filter(key=key).exists())

    def test_csrf_is_still_enforced(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post("/app/login/reception/", {"username": "owner", "password": "wrong"}).status_code, 403)

    def test_idle_session_expires(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["security_last_seen"] = (timezone.now() - timedelta(minutes=31)).timestamp()
        session.save()
        response = self.client.get("/app/")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_active_session_is_not_logged_out(self):
        self.client.force_login(self.user)
        self.client.get("/app/")
        self.assertIn("_auth_user_id", self.client.session)

    def test_security_headers_on_login_and_api_errors(self):
        response = self.client.get("/app/login/")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("camera=()", response["Permissions-Policy"])
        response = self.client.get("/api/patients/")
        self.assertIn("no-store", response["Cache-Control"])

    def test_basic_auth_is_disabled(self):
        import base64
        credentials = base64.b64encode(b"owner:Long-test-password-129!").decode()
        response = self.client.get("/api/patients/", HTTP_AUTHORIZATION="Basic " + credentials)
        self.assertEqual(response.status_code, 403)

    @override_settings(PRODUCTION_MODE=True)
    def test_fake_payment_checkout_disabled_in_production(self):
        self.client.force_login(self.user)
        response = self.client.post("/api/payments/deposits/checkout/", {}, content_type="application/json")
        self.assertEqual(response.status_code, 503)

    def test_cleanup_only_removes_expired_buckets(self):
        self.attempt()
        LoginAttemptBucket.objects.create(key="expired", started_at=timezone.now() - timedelta(days=1))
        call_command("clear_login_attempts", stdout=StringIO())
        self.assertFalse(LoginAttemptBucket.objects.filter(key="expired").exists())
        self.assertEqual(LoginAttemptBucket.objects.count(), 2)


class ProductionGuardTests(TestCase):
    def test_unsafe_configuration_rejected_without_leaking_secret(self):
        with override_settings(DEBUG=True, SECRET_KEY="secret-value-do-not-print", ALLOWED_HOSTS=["*"]):
            with self.assertRaises(CommandError) as error:
                call_command("check_production", stdout=StringIO())
        self.assertIn("Production configuration rejected", str(error.exception))
        self.assertNotIn("secret-value-do-not-print", str(error.exception))

    @override_settings(DEBUG=False, SECRET_KEY="test-secret-0123456789-abcdefghijklmnopqrstuvwxyz-ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        ALLOWED_HOSTS=["clinic.example.org", "127.0.0.1"], SECURE_SSL_REDIRECT=True, SECURE_HSTS_SECONDS=300,
        SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
        DATABASES={"default": {"ENGINE": "django.db.backends.postgresql", "PASSWORD": "strong-test-key-0123456789-abcdef"}})
    def test_explicit_safe_configuration_accepted(self):
        self.assertEqual(configuration_errors(settings), [])
        with override_settings(PRODUCTION_MODE=True):
            output = StringIO()
            call_command("check_production", stdout=output)
            self.assertIn("Production configuration checks passed", output.getvalue())

    def test_weak_database_secret_rejected(self):
        with override_settings(DATABASES={"default": {"ENGINE": "django.db.backends.postgresql", "PASSWORD": "replace_me"}}):
            self.assertTrue(any("PostgreSQL password" in failure for failure in configuration_errors(settings)))

    def test_development_mode_cannot_pass_production_command(self):
        with self.assertRaises(CommandError) as error:
            call_command("check_production", stdout=StringIO())
        self.assertIn("DJANGO_PRODUCTION must be True", str(error.exception))
