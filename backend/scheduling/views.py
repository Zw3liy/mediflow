from rest_framework import status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import action

from tenancy.context import require_membership
from tenancy.models import Membership
from .services import approve_booking, book, reject_booking
from .models import Appointment, Service
from .serializers import AppointmentSerializer, ServiceSerializer
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)

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

        queryset = Appointment.objects.filter(
            practice=membership.practice,
        ).select_related(
            "practice",
            "patient",
            "practitioner",
            "service",
        )

        if membership.role in PRACTITIONER_ROLES:
            queryset = queryset.filter(
                practitioner=self.request.user,
            )

        requested_status = self.request.query_params.get(
            "status"
        )

        if requested_status:
            valid_statuses = {
                value
                for value, _label in Appointment.Status.choices
            }

            if requested_status not in valid_statuses:
                raise ValidationError(
                    {
                        "status": "Invalid appointment status.",
                    }
                )

            queryset = queryset.filter(
                status=requested_status,
            )

        return queryset

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

        values = serializer.validated_data

        try:
            appointment = book(
                practice=membership.practice,
                patient=values["patient"],
                practitioner=values["practitioner"],
                service=values["service"],
                starts_at=values["starts_at"],
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {"detail": error.messages},
            ) from error

        serializer.instance = appointment
        
    def perform_update(self, serializer):
        membership = self.get_membership()
        self.validate_related_objects(serializer, membership)
        serializer.save(practice=membership.practice)

    @action(
        detail=True,
        methods=["post"],
    )
    def approve(self, request, pk=None):
        membership = self.get_membership()

        try:
            appointment = approve_booking(
                appointment_id=pk,
                practice=membership.practice,
                actor=request.user,
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {"detail": error.messages},
            ) from error

        serializer = self.get_serializer(appointment)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
    )
    def reject(self, request, pk=None):
        membership = self.get_membership()
        reason = request.data.get("reason") or ""

        try:
            appointment = reject_booking(
                appointment_id=pk,
                practice=membership.practice,
                actor=request.user,
                reason=reason,
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {"detail": error.messages},
            ) from error

        serializer = self.get_serializer(appointment)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )
