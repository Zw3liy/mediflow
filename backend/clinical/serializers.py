from rest_framework import serializers

from .models import Prescription, PrescriptionItem


class PrescriptionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrescriptionItem
        fields = [
            "id",
            "medication_name",
            "dosage",
            "route",
            "frequency",
            "duration",
            "quantity",
            "instructions",
        ]
        read_only_fields = [
            "id",
        ]


class PrescriptionSerializer(serializers.ModelSerializer):
    items = PrescriptionItemSerializer(
        many=True,
    )

    class Meta:
        model = Prescription
        fields = [
            "id",
            "encounter",
            "prescribed_by",
            "status",
            "general_instructions",
            "issued_at",
            "created_at",
            "updated_at",
            "items",
        ]
        read_only_fields = [
            "id",
            "prescribed_by",
            "status",
            "issued_at",
            "created_at",
            "updated_at",
        ]
