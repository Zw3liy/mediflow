from rest_framework import serializers

from .models import DepositPayment


class CreateDepositCheckoutSerializer(serializers.Serializer):
    appointment_id = serializers.IntegerField(min_value=1)


class DepositPaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DepositPayment
        fields = [
            "id",
            "appointment",
            "amount_cents",
            "currency",
            "status",
            "provider",
            "provider_reference",
            "checkout_url",
            "paid_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields