from django.db import transaction
from auditlog.services import record_audit_event

from .models import PrescriptionDocument


CLEAN_RESULT = "clean"
INFECTED_RESULT = "infected"


@transaction.atomic
def scan_prescription_document(
    *,
    document_id,
    storage,
    scanner,
):
    document = (
        PrescriptionDocument.objects.select_for_update()
        .get(pk=document_id)
    )

    if (
        document.scan_status
        != PrescriptionDocument.ScanStatus.PENDING
    ):
        return document

    try:
        content = storage.read(
            object_key=document.object_key,
        )
        result = scanner.scan(
            content=content,
        )
    except Exception:
        result = None

    if result == CLEAN_RESULT:
        document.scan_status = (
            PrescriptionDocument.ScanStatus.CLEAN
        )
    elif result == INFECTED_RESULT:
        document.scan_status = (
            PrescriptionDocument.ScanStatus.INFECTED
        )
        document.released_to_patient_at = None
    else:
        document.scan_status = (
            PrescriptionDocument.ScanStatus.FAILED
        )
        document.released_to_patient_at = None

    document.save(
        update_fields=[
            "scan_status",
            "released_to_patient_at",
        ]
    )

    record_audit_event(
        practice=document.practice,
        actor=None,
        action=f"document.scan_{document.scan_status}",
        object_type="prescription_document",
        object_id=document.id,
        purpose="Scan prescription document for malware",
        outcome=(
            "success"
            if document.scan_status
            in {
                PrescriptionDocument.ScanStatus.CLEAN,
                PrescriptionDocument.ScanStatus.INFECTED,
            }
            else "failed"
        ),
        metadata={
            "scan_status": document.scan_status,
        },
    )

    return document


import socket
import struct

from django.conf import settings

from .storage import get_document_storage


class ClamAVScanner:
    def __init__(
        self,
        *,
        host="127.0.0.1",
        port=3310,
        timeout=30,
    ):
        self.host = host
        self.port = port
        self.timeout = timeout

    def scan(self, *, content):
        with socket.create_connection(
            (self.host, self.port),
            timeout=self.timeout,
        ) as connection:
            connection.sendall(b"zINSTREAM\0")

            for offset in range(0, len(content), 8192):
                chunk = content[offset : offset + 8192]
                connection.sendall(
                    struct.pack("!I", len(chunk))
                )
                connection.sendall(chunk)

            connection.sendall(struct.pack("!I", 0))

            response = bytearray()

            while True:
                chunk = connection.recv(4096)

                if not chunk:
                    break

                response.extend(chunk)

                if b"\0" in chunk:
                    break

        message = bytes(response).rstrip(b"\0").decode(
            "utf-8",
            errors="replace",
        )

        if message.endswith("OK"):
            return CLEAN_RESULT

        if message.endswith("FOUND"):
            return INFECTED_RESULT

        raise RuntimeError(
            f"Malware scanner returned an invalid response: {message}"
        )


def get_document_scanner():
    return ClamAVScanner(
        host=getattr(
            settings,
            "CLAMAV_HOST",
            "127.0.0.1",
        ),
        port=getattr(
            settings,
            "CLAMAV_PORT",
            3310,
        ),
        timeout=getattr(
            settings,
            "CLAMAV_TIMEOUT",
            30,
        ),
    )
