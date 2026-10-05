from unittest.mock import patch

from django.test import SimpleTestCase

from .scanning import (
    CLEAN_RESULT,
    INFECTED_RESULT,
    ClamAVScanner,
)


class FakeClamAVConnection:
    def __init__(self, response):
        self.response = response
        self.sent = []
        self.received = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def sendall(self, content):
        self.sent.append(content)

    def recv(self, size):
        if self.received:
            return b""

        self.received = True
        return self.response


class ClamAVScannerTests(SimpleTestCase):
    def scan_response(self, response):
        connection = FakeClamAVConnection(response)

        with patch(
            "documents.scanning.socket.create_connection",
            return_value=connection,
        ) as create_connection:
            result = ClamAVScanner(
                host="clamav",
                port=3310,
                timeout=12,
            ).scan(
                content=b"%PDF-1.7\ncontent",
            )

        create_connection.assert_called_once_with(
            ("clamav", 3310),
            timeout=12,
        )
        self.assertEqual(
            connection.sent[0],
            b"zINSTREAM\0",
        )
        self.assertEqual(
            connection.sent[-1],
            b"\x00\x00\x00\x00",
        )

        return result

    def test_clean_clamav_response_returns_clean(self):
        result = self.scan_response(
            b"stream: OK\0",
        )

        self.assertEqual(result, CLEAN_RESULT)

    def test_infected_clamav_response_returns_infected(self):
        result = self.scan_response(
            b"stream: Eicar-Test-Signature FOUND\0",
        )

        self.assertEqual(result, INFECTED_RESULT)

    def test_invalid_clamav_response_raises_error(self):
        with self.assertRaisesMessage(
            RuntimeError,
            "Malware scanner returned an invalid response",
        ):
            self.scan_response(
                b"stream: scanner unavailable ERROR\0",
            )
