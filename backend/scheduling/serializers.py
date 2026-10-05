from rest_framework import serializers

from .models import Appointment, Service



class ServiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Service
        fields = [
            "id",
            "practice",
            "name",
            "duration_minutes",
            "price_cents",
            "deposit_cents",
        ]
        read_only_fields = [
            "id",
            "practice",
        ]


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = [
            "id",
            "practice",
            "patient",
            "practitioner",
            "service",
            "starts_at",
            "ends_at",
            "status",
            "hold_expires_at",
            "reviewed_by",
            "reviewed_at",
            "decision_reason",
        ]
        read_only_fields = [
            "id",
            "practice",
            "ends_at",
            "status",
            "hold_expires_at",
            "reviewed_by",
            "reviewed_at",
            "decision_reason",
        ]

    def validate(self, attributes):
        # The booking service calculates ends_at for both creates and updates.
        return attributes
