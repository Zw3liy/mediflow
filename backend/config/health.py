import socket
from pathlib import Path
from tempfile import NamedTemporaryFile

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_GET


def database_is_ready():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            return cursor.fetchone()[0] == 1
    except Exception:
        return False


def storage_is_ready():
    root = Path(
        getattr(
            settings,
            "DOCUMENT_STORAGE_ROOT",
            settings.BASE_DIR / "private_documents",
        )
    )

    try:
        root.mkdir(
            parents=True,
            exist_ok=True,
        )

        with NamedTemporaryFile(
            dir=root,
            prefix=".health-",
        ) as probe:
            probe.write(b"ready")
            probe.flush()

        return True
    except OSError:
        return False


def clamav_is_ready():
    host = getattr(
        settings,
        "CLAMAV_HOST",
        "127.0.0.1",
    )
    port = getattr(
        settings,
        "CLAMAV_PORT",
        3310,
    )
    timeout = min(
        getattr(
            settings,
            "CLAMAV_TIMEOUT",
            30,
        ),
        5,
    )

    try:
        with socket.create_connection(
            (host, port),
            timeout=timeout,
        ) as connection:
            connection.sendall(b"zPING\0")
            response = connection.recv(16)

        return response.rstrip(b"\0") == b"PONG"
    except OSError:
        return False


@require_GET
def live(request):
    return JsonResponse(
        {
            "status": "ok",
        }
    )


@require_GET
def ready(request):
    checks = {}

    for name, checker in [
        ("database", database_is_ready),
        ("storage", storage_is_ready),
        ("clamav", clamav_is_ready),
    ]:
        try:
            checks[name] = bool(checker())
        except Exception:
            checks[name] = False

    is_ready = all(checks.values())

    return JsonResponse(
        {
            "status": (
                "ready"
                if is_ready
                else "unavailable"
            ),
            "checks": checks,
        },
        status=200 if is_ready else 503,
    )
