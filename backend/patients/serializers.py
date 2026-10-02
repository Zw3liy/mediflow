from rest_framework import serializers

from .models import Patient


class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = [
            "id",
            "practice",
            "portal_user",
            "file_number",
            "given_name",
            "family_name",
            "date_of_birth",
            "mobile",
            "email",
            "emergency_contact_name",
            "emergency_contact_mobile",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "practice",
            "portal_user",
            "created_at",
            "updated_at",
        ]
