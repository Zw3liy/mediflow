from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.test import Client, SimpleTestCase, override_settings


class ProductionStaticAssetTests(SimpleTestCase):
    def test_collected_admin_assets_are_served_with_debug_disabled(self):
        with TemporaryDirectory() as root, TemporaryDirectory() as private_root:
            Path(private_root, "private.pdf").write_bytes(b"private prescription")
            with override_settings(
                DEBUG=False, STATIC_ROOT=root, STATIC_URL="/static/",
                SECURE_SSL_REDIRECT=False, ALLOWED_HOSTS=["testserver"],
                DOCUMENT_STORAGE_ROOT=private_root,
            ):
                call_command("collectstatic", interactive=False, verbosity=0)
                client = Client()
                for asset, mime in [
                    ("admin/css/base.css", "text/css"),
                    ("admin/js/theme.js", "text/javascript"),
                ]:
                    with self.subTest(asset=asset):
                        response = client.get(f"/static/{asset}")
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(mime, response["Content-Type"])
                        content = b"".join(response.streaming_content)
                        self.assertTrue(content)
                        response.close()
                self.assertEqual(client.get("/static/private.pdf").status_code, 404)
                self.assertEqual(client.get("/private_documents/private.pdf").status_code, 404)
