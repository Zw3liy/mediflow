from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.permissions import IsAuthenticated

from tenancy.context import require_membership

from .models import Patient
from .serializers import PatientSerializer


STAFF_ROLES = [
    "owner",
    "doctor",
    "nurse",
    "reception",
]


class PatientViewSet(viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = ["active"]
    search_fields = [
        "file_number",
        "given_name",
        "family_name",
        "mobile",
        "email",
    ]
    ordering_fields = [
        "family_name",
        "given_name",
        "created_at",
    ]
    ordering = ["family_name", "given_name"]

    def get_membership(self):
        return require_membership(
            user=self.request.user,
            practice_id=self.request.headers.get("X-Practice-ID"),
            roles=STAFF_ROLES,
        )

    def get_queryset(self):
        membership = self.get_membership()

        return Patient.objects.filter(
            practice=membership.practice,
        ).select_related(
            "practice",
            "portal_user",
        )

    def perform_create(self, serializer):
        membership = self.get_membership()
        serializer.save(practice=membership.practice)
