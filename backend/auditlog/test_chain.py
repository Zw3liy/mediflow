from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase

from tenancy.models import Practice

from .models import AuditEvent
from .services import (
    AuditChainError,
    record_audit_event,
    verify_audit_chain,
)


User = get_user_model()


class AuditChainTests(TestCase):
    def setUp(self):
        self.practice = Practice.objects.create(
            name="Audit Practice",
        )
        self.other_practice = Practice.objects.create(
            name="Other Audit Practice",
        )
        self.actor = User.objects.create_user(
            username="audit-actor",
            password="safe-test-password",
        )

    def record(self, **overrides):
        values = {
            "practice": self.practice,
            "actor": self.actor,
            "action": "appointment.approved",
            "object_type": "appointment",
            "object_id": "appointment-123",
            "purpose": "Approve requested appointment",
            "outcome": "success",
            "metadata": {
                "status": "held",
            },
        }
        values.update(overrides)

        return record_audit_event(**values)

    def test_first_event_starts_valid_hash_chain(self):
        event = self.record()

        self.assertEqual(event.previous_hash, "")
        self.assertEqual(len(event.event_hash), 64)
        self.assertTrue(
            verify_audit_chain(practice=self.practice)
        )

    def test_later_event_links_to_previous_event_hash(self):
        first = self.record()
        second = self.record(
            action="prescription.created",
            object_type="prescription",
            object_id="prescription-456",
            purpose="Create prescription",
        )

        self.assertEqual(
            second.previous_hash,
            first.event_hash,
        )
        self.assertNotEqual(
            second.event_hash,
            first.event_hash,
        )
        self.assertTrue(
            verify_audit_chain(practice=self.practice)
        )

    def test_each_practice_has_an_independent_chain(self):
        first_practice_event = self.record()
        other_practice_event = self.record(
            practice=self.other_practice,
            action="document.uploaded",
            object_type="prescription_document",
            object_id="document-789",
            purpose="Upload prescription document",
        )

        self.assertEqual(
            first_practice_event.previous_hash,
            "",
        )
        self.assertEqual(
            other_practice_event.previous_hash,
            "",
        )
        self.assertTrue(
            verify_audit_chain(practice=self.practice)
        )
        self.assertTrue(
            verify_audit_chain(practice=self.other_practice)
        )

    def test_database_tampering_breaks_chain_verification(self):
        event = self.record()

        table = connection.ops.quote_name(
            AuditEvent._meta.db_table
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {table} "
                "SET purpose = %s "
                "WHERE id = %s",
                [
                    "Tampered purpose",
                    event.id,
                ],
            )

        self.assertFalse(
            verify_audit_chain(practice=self.practice)
        )

    def test_audit_events_cannot_be_updated_through_model(self):
        event = self.record()
        event.purpose = "Changed purpose"

        with self.assertRaisesMessage(
            AuditChainError,
            "Audit events are append-only.",
        ):
            event.save()

    def test_audit_events_cannot_be_deleted_through_model(self):
        event = self.record()

        with self.assertRaisesMessage(
            AuditChainError,
            "Audit events are append-only.",
        ):
            event.delete()

    def test_queryset_update_and_delete_are_blocked(self):
        event = self.record()
        queryset = AuditEvent.objects.filter(pk=event.pk)

        with self.assertRaisesMessage(
            AuditChainError,
            "Audit events are append-only.",
        ):
            queryset.update(
                purpose="Changed purpose",
            )

        with self.assertRaisesMessage(
            AuditChainError,
            "Audit events are append-only.",
        ):
            queryset.delete()

    def test_event_metadata_is_canonical_and_order_independent(self):
        first = self.record(
            object_id="canonical-1",
            metadata={
                "b": 2,
                "a": 1,
            },
        )
        second = self.record(
            object_id="canonical-2",
            metadata={
                "a": 1,
                "b": 2,
            },
        )

        self.assertEqual(
            first.metadata,
            {
                "b": 2,
                "a": 1,
            },
        )
        self.assertTrue(
            verify_audit_chain(practice=self.practice)
        )
        self.assertEqual(
            second.previous_hash,
            first.event_hash,
        )
