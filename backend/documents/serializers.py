from rest_framework import serializers

from .models import PrescriptionDocument


class StaffPrescriptionDocumentSerializer(
    serializers.ModelSerializer,
):
    class Meta:
        model = PrescriptionDocument
        fields = [
            "id",
            "practice",
            "prescription",
            "uploaded_by",
            "original_name",
            "object_key",
            "content_type",
            "size_bytes",
            "sha256",
            "scan_status",
            "released_to_patient_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "practice",
            "uploaded_by",
            "scan_status",
            "released_to_patient_at",
            "created_at",
        ]


class PatientPrescriptionDocumentSerializer(
    serializers.ModelSerializer,
):
    class Meta:
        model = PrescriptionDocument
        fields = [
            "id",
            "prescription",
            "original_name",
            "content_type",
            "size_bytes",
            "released_to_patient_at",
            "created_at",
        ]
        read_only_fields = fields


class PrescriptionDocumentUploadSerializer(serializers.Serializer):
    prescription = serializers.PrimaryKeyRelatedField(
        queryset=PrescriptionDocument._meta.get_field(
            "prescription"
        ).remote_field.model.objects.all(),
    )
    file = serializers.FileField()
