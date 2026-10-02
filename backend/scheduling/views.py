from rest_framework import viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated

from tenancy.context import require_membership
from tenancy.models import Membership

from .models import Appointment, Service
from .serializers import AppointmentSerializer, ServiceSerializer


STAFF_ROLES = [
    "owner",
    "doctor",
    "nurse",
    "reception",
]

PRACTITIONER_ROLES = [
    "doctor",
    "nurse",
]


class PracticeViewSetMixin:
    permission_classes = [IsAuthenticated]

    def get_membership(self):
        return require_membership(
            user=self.request.user,
            practice_id=self.request.headers.get("X-Practice-ID"),
            roles=STAFF_ROLES,
        )


class ServiceViewSet(PracticeViewSetMixin, viewsets.ModelViewSet):
    serializer_class = ServiceSerializer

    def get_queryset(self):
        membership = self.get_membership()

        return Service.objects.filter(
            practice=membership.practice,
        ).select_related("practice")

    def perform_create(self, serializer):
        membership = self.get_membership()
        serializer.save(practice=membership.practice)


class AppointmentViewSet(
    PracticeViewSetMixin,
    viewsets.ModelViewSet,
):
    serializer_class = AppointmentSerializer

    def get_queryset(self):
        membership = self.get_membership()

        return Appointment.objects.filter(
            practice=membership.practice,
        ).select_related(
            "practice",
            "patient",
            "practitioner",
            "service",
        )

    def validate_related_objects(self, serializer, membership):
        instance = serializer.instance
        values = serializer.validated_data

        patient = values.get(
            "patient",
            getattr(instance, "patient", None),
        )
        service = values.get(
            "service",
            getattr(instance, "service", None),
        )
        practitioner = values.get(
            "practitioner",
            getattr(instance, "practitioner", None),
        )

        errors = {}

        if patient and patient.practice_id != membership.practice_id:
            errors["patient"] = (
                "The patient does not belong to this practice."
            )

        if service and service.practice_id != membership.practice_id:
            errors["service"] = (
                "The service does not belong to this practice."
            )

        practitioner_allowed = Membership.objects.filter(
            practice=membership.practice,
            user=practitioner,
            active=True,
            role__in=PRACTITIONER_ROLES,
        ).exists()

        if practitioner and not practitioner_allowed:
            errors["practitioner"] = (
                "The practitioner is not active in this practice."
            )

        if errors:
            raise ValidationError(errors)

    def perform_create(self, serializer):
        membership = self.get_membership()
        self.validate_related_objects(serializer, membership)
        serializer.save(practice=membership.practice)

    def perform_update(self, serializer):
        membership = self.get_membership()
        self.validate_related_objects(serializer, membership)
        serializer.save(practice=membership.practice)
