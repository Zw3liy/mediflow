from django.core.exceptions import(
    ValidationError as DjangoValidationError,
)
from rest_framework.exceptions import (
    ValidationError as ApiValidationError,
)

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response

from tenancy.context import require_membership

from .sandbox import SandboxGateway
from .serializers import (
    CreateDepositCheckoutSerializer,
    DepositPaymentSerializer,
)
from . services import create_deposit_checkout

STAFF_ROLES = [
    "owner",
    "doctor",
    "nurse",
    "receptionist",
]

class CreateDepositCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request,):
        input_serializer = CreateDepositCheckoutSerializer(
            data=request.data,
        )
        input_serializer.is_valid(raise_exception=True)

        membership = require_membership(
            user=request.user,
            practice_id=request.headers.get("X-Practice-ID"),
            roles=STAFF_ROLES,
        )
        try:
            payment = create_deposit_checkout(
                appointment_id=input_serializer.validated_data["appointment_id"],
                practice=membership.practice,
                gateway=SandboxGateway(),
            )
            
        except DjangoValidationError as error:
            raise ApiValidationError(
                {"detail":error.message},
                )from error

        output_serializer = DepositPaymentSerializer(payment)

        return Response(output_serializer.data)