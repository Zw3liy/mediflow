from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from documents.models import PatientDocumentScan
from documents.storage import get_document_storage


class Command(BaseCommand):
    help = 'Remove unreviewed document scan drafts older than 24 hours.'

    def handle(self, *args, **options):
        count = 0
        storage = get_document_storage()
        for pk in PatientDocumentScan.objects.filter(reviewed_at__isnull=True,
                created_at__lt=timezone.now() - timedelta(hours=24)).values_list('pk', flat=True).iterator():
            with transaction.atomic():
                scan = PatientDocumentScan.objects.select_for_update().filter(pk=pk, reviewed_at__isnull=True,
                    created_at__lt=timezone.now() - timedelta(hours=24)).first()
                if scan is None:
                    continue
                storage.delete(object_key=scan.original_key)
                storage.delete(object_key=scan.pdf_key)
                scan.delete()
                count += 1
        self.stdout.write(f'Removed {count} expired document drafts.')
