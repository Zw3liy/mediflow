from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import Client, TransactionTestCase

from securityguard.middleware import bucket_key
from securityguard.models import LoginAttemptBucket


@skipUnless(connection.vendor == "postgresql", "PostgreSQL row-locking test")
class LoginConcurrencyTests(TransactionTestCase):
    def test_concurrent_login_attempts_cannot_bypass_limit(self):
        barrier = Barrier(6)

        def attempt(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return Client().post("/app/login/patient/", {"username": "missing-user", "password": "wrong"}).status_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=6) as executor:
            statuses = list(executor.map(attempt, range(6)))
        self.assertEqual(statuses.count(429), 1)
        self.assertEqual(LoginAttemptBucket.objects.get(key=bucket_key("account", "missing-user")).attempts, 5)
