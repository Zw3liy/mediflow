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

from .models import PrescriptionDocument
from .serializers import (
    PatientPrescriptionDocumentSerializer,
    StaffPrescriptionDocumentSerializer,
)
from .services import (
    register_prescription_document,
    release_prescription_document,
)


DOCUMENT_ROLES = [
    Membership.Role.OWNER,
    Membership.Role.RECEPTION,
    Membership.Role.PATIENT,
]

DOCUMENT_STAFF_ROLES = {
    Membership.Role.OWNER,
    Membership.Role.RECEPTION,
}


class PrescriptionDocumentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    permission_classes = [IsAuthenticated]

    def get_membership(self):
        return require_membership(
            user=self.request.user,
            practice_id=self.request.headers.get("X-Practice-ID"),
            roles=DOCUMENT_ROLES,
        )

    def get_serializer_class(self):
        membership = self.get_membership()

        if membership.role == Membership.Role.PATIENT:
            return PatientPrescriptionDocumentSerializer

        return StaffPrescriptionDocumentSerializer

    def get_queryset(self):
        membership = self.get_membership()

        queryset = PrescriptionDocument.objects.filter(
            practice=membership.practice,
        ).select_related(
            "practice",
            "prescription",
            "prescription__encounter",
            "prescription__encounter__patient",
            "uploaded_by",
        )

        if membership.role in DOCUMENT_STAFF_ROLES:
            return queryset

        return queryset.filter(
            prescription__encounter__patient__portal_user=(
                self.request.user
            ),
            scan_status=PrescriptionDocument.ScanStatus.CLEAN,
            released_to_patient_at__isnull=False,
        )

    def perform_create(self, serializer):
        membership = self.get_membership()

        if membership.role not in DOCUMENT_STAFF_ROLES:
            raise PermissionDenied(
                "Only reception or owner staff may register files."
            )

        values = serializer.validated_data
        prescription = values["prescription"]

        if (
            prescription.encounter.practice_id
            != membership.practice_id
        ):
            raise ValidationError(
                {
                    "prescription": (
                        "The prescription does not belong "
                        "to this practice."
                    ),
                }
            )

        try:
            document = register_prescription_document(
                prescription_id=prescription.id,
                practice=membership.practice,
                actor=self.request.user,
                original_name=values["original_name"],
                object_key=values["object_key"],
                content_type=values["content_type"],
                size_bytes=values["size_bytes"],
                sha256=values["sha256"],
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {
                    "detail": error.messages,
                }
            ) from error

        serializer.instance = document

    @action(
        detail=True,
        methods=["post"],
    )
    def release(self, request, pk=None):
        membership = self.get_membership()

        if membership.role not in DOCUMENT_STAFF_ROLES:
            raise PermissionDenied(
                "Only reception or owner staff may release files."
            )

        try:
            document = release_prescription_document(
                document_id=pk,
                practice=membership.practice,
                actor=request.user,
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {
                    "detail": error.messages,
                }
            ) from error

        serializer = self.get_serializer(document)

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )
