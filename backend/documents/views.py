from django.conf import settings
from django.http import HttpResponse
from django.utils.http import content_disposition_header
from django.core.exceptions import (
    ValidationError as DjangoValidationError,
)
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tenancy.context import require_membership
from tenancy.models import Membership

from .models import PrescriptionDocument
from .serializers import (
    PatientPrescriptionDocumentSerializer,
    PrescriptionDocumentUploadSerializer,
    StaffPrescriptionDocumentSerializer,
)
from .storage import DocumentStorageError, get_document_storage
from .storage_services import (
    create_patient_download_token,
    resolve_patient_download_token,
    upload_prescription_document,
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


class DocumentStorageUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Document storage is temporarily unavailable."


class PrescriptionDocumentViewSet(
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
        if self.action == "upload":
            return PrescriptionDocumentUploadSerializer

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

    @action(
        detail=False,
        methods=["post"],
    )
    def upload(self, request):
        membership = self.get_membership()

        if membership.role not in DOCUMENT_STAFF_ROLES:
            raise PermissionDenied(
                "Only reception or owner staff may upload files."
            )

        input_serializer = self.get_serializer(
            data=request.data,
        )
        input_serializer.is_valid(
            raise_exception=True,
        )

        prescription = input_serializer.validated_data[
            "prescription"
        ]

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
            document = upload_prescription_document(
                prescription_id=prescription.id,
                practice=membership.practice,
                actor=request.user,
                uploaded_file=input_serializer.validated_data["file"],
                storage=get_document_storage(),
            )
        except DjangoValidationError as error:
            raise ValidationError(
                {
                    "detail": error.messages,
                }
            ) from error
        except DocumentStorageError as error:
            raise DocumentStorageUnavailable() from error

        output_serializer = StaffPrescriptionDocumentSerializer(
            document,
            context=self.get_serializer_context(),
        )

        return Response(
            output_serializer.data,
            status=status.HTTP_201_CREATED,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="download-token",
    )
    def download_token(self, request, pk=None):
        document = self.get_object()

        token = create_patient_download_token(
            document=document,
            user=request.user,
        )

        return Response(
            {
                "token": token,
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["get"],
    )
    def download(self, request, pk=None):
        document = self.get_object()
        token = request.query_params.get("token", "")

        resolved_document = resolve_patient_download_token(
            token=token,
            user=request.user,
            max_age=getattr(
                settings,
                "DOCUMENT_DOWNLOAD_TOKEN_MAX_AGE",
                300,
            ),
        )

        if resolved_document.id != document.id:
            raise PermissionDenied(
                "Document is not available to this patient."
            )

        try:
            content = get_document_storage().read(
                object_key=document.object_key,
            )
        except DocumentStorageError as error:
            raise DocumentStorageUnavailable() from error

        response = HttpResponse(
            content,
            content_type=document.content_type,
        )
        response["Content-Disposition"] = (
            content_disposition_header(
                True,
                document.original_name,
            )
        )

        return response
