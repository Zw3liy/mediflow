from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse


class HealthEndpointTests(TestCase):
    def test_liveness_does_not_require_dependencies(self):
        with (
            patch(
                "config.health.database_is_ready",
                side_effect=RuntimeError("Database unavailable"),
            ),
            patch(
                "config.health.storage_is_ready",
                side_effect=RuntimeError("Storage unavailable"),
            ),
            patch(
                "config.health.clamav_is_ready",
                side_effect=RuntimeError("ClamAV unavailable"),
            ),
        ):
            response = self.client.get(
                reverse("health-live"),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
            },
        )

    @patch(
        "config.health.clamav_is_ready",
        return_value=True,
    )
    @patch(
        "config.health.storage_is_ready",
        return_value=True,
    )
    @patch(
        "config.health.database_is_ready",
        return_value=True,
    )
    def test_readiness_passes_when_dependencies_are_ready(
        self,
        database_ready,
        storage_ready,
        clamav_ready,
    ):
        response = self.client.get(
            reverse("health-ready"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ready",
                "checks": {
                    "database": True,
                    "storage": True,
                    "clamav": True,
                },
            },
        )

    @patch(
        "config.health.clamav_is_ready",
        return_value=True,
    )
    @patch(
        "config.health.storage_is_ready",
        return_value=True,
    )
    @patch(
        "config.health.database_is_ready",
        return_value=False,
    )
    def test_readiness_fails_when_database_is_unavailable(
        self,
        database_ready,
        storage_ready,
        clamav_ready,
    ):
        response = self.client.get(
            reverse("health-ready"),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["checks"]["database"],
            False,
        )

    @patch(
        "config.health.clamav_is_ready",
        return_value=True,
    )
    @patch(
        "config.health.storage_is_ready",
        return_value=False,
    )
    @patch(
        "config.health.database_is_ready",
        return_value=True,
    )
    def test_readiness_fails_when_storage_is_unavailable(
        self,
        database_ready,
        storage_ready,
        clamav_ready,
    ):
        response = self.client.get(
            reverse("health-ready"),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["checks"]["storage"],
            False,
        )

    @patch(
        "config.health.clamav_is_ready",
        return_value=False,
    )
    @patch(
        "config.health.storage_is_ready",
        return_value=True,
    )
    @patch(
        "config.health.database_is_ready",
        return_value=True,
    )
    def test_readiness_fails_when_clamav_is_unavailable(
        self,
        database_ready,
        storage_ready,
        clamav_ready,
    ):
        response = self.client.get(
            reverse("health-ready"),
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json()["checks"]["clamav"],
            False,
        )
