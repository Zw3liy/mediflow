from django.core.management.base import BaseCommand

from documents.models import PrescriptionDocument
from documents.scanning import (
    get_document_scanner,
    scan_prescription_document,
)
from documents.storage import get_document_storage


class Command(BaseCommand):
    help = "Scan pending prescription documents for malware."

    def handle(self, *args, **options):
        document_ids = list(
            PrescriptionDocument.objects.filter(
                scan_status=(
                    PrescriptionDocument.ScanStatus.PENDING
                ),
            ).values_list(
                "id",
                flat=True,
            )
        )

        storage = get_document_storage()
        scanner = get_document_scanner()

        for document_id in document_ids:
            scan_prescription_document(
                document_id=document_id,
                storage=storage,
                scanner=scanner,
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Scanned {len(document_ids)} pending document(s)."
            )
        )
