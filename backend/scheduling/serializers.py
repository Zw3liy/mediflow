from rest_framework import serializers
from .services import book

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
        ]
        read_only_fields = [
            "id",
            "practice",
            "ends_at",
            "status",
            "hold_expires_at",
        ]

    def validate(self, attributes):
        starts_at = attributes.get(
            "starts_at",
            getattr(self.instance, "starts_at", None),
        )
        ends_at = attributes.get(
            "ends_at",
            getattr(self.instance, "ends_at", None),
        )

        if starts_at and ends_at and ends_at <= starts_at:
            raise serializers.ValidationError(
                {
                    "ends_at": (
                        "The appointment must end after it starts."
                    ),
                },
            )

        return attributes
