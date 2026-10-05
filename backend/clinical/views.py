from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tenancy.context import require_membership
from tenancy.models import Membership

from .models import Prescription
from .serializers import PrescriptionSerializer
from .services import create_prescription, issue_prescription


PRESCRIPTION_ROLES = [
    Membership.Role.DOCTOR,
    Membership.Role.PATIENT,
]


class PrescriptionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = PrescriptionSerializer
    permission_classes = [IsAuthenticated]

    def get_membership(self):
        return require_membership(
            user=self.request.user,
            practice_id=self.request.headers.get("X-Practice-ID"),
            roles=PRESCRIPTION_ROLES,
        )

    def get_queryset(self):
        membership = self.get_membership()

        queryset = Prescription.objects.filter(
            encounter__practice=membership.practice,
        ).select_related(
            "encounter",
            "encounter__patient",
            "prescribed_by",
        ).prefetch_related(
            "items",
        )

        if membership.role == Membership.Role.DOCTOR:
            return queryset.filter(
                prescribed_by=self.request.user,
            )

        return queryset.filter(
            encounter__patient__portal_user=self.request.user,
            status=Prescription.Status.ISSUED,
        )

    def perform_create(self, serializer):
        membership = self.get_membership()

        if membership.role != Membership.Role.DOCTOR:
            raise PermissionDenied(
                "Only doctors may create prescriptions."
            )

        values = serializer.validated_data
        encounter = values["encounter"]

        if encounter.practice_id != membership.practice_id:
            raise ValidationError(
                {
                    "encounter": (
                        "The encounter does not belong to this practice."
                    ),
                }
            )

        try:
            prescription = create_prescription(
                encounter_id=encounter.id,
                actor=self.request.user,
                general_instructions=values.get(
                    "general_instructions",
                    "",
                ),
                items=values["items"],
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {
                    "detail": error.messages,
                }
            ) from error

        serializer.instance = prescription

    @action(
        detail=True,
        methods=["post"],
    )
    def issue(self, request, pk=None):
        membership = self.get_membership()

        if membership.role != Membership.Role.DOCTOR:
            raise PermissionDenied(
                "Only doctors may issue prescriptions."
            )

        try:
            prescription = issue_prescription(
                prescription_id=pk,
                actor=request.user,
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {
                    "detail": error.messages,
                }
            ) from error

        serializer = self.get_serializer(prescription)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )
