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
            "reason_for_visit",
            "blood_pressure_systolic",
            "blood_pressure_diastolic",
            "blood_pressure_recorded_at",
            "blood_pressure_recorded_by",
            "doctor_approved_at",
            "called_at",
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
            "blood_pressure_systolic",
            "blood_pressure_diastolic",
            "blood_pressure_recorded_at",
            "blood_pressure_recorded_by",
            "doctor_approved_at",
            "called_at",
        ]

    reason_for_visit = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, attributes):
        # The booking service calculates ends_at for both creates and updates.
        return attributes
