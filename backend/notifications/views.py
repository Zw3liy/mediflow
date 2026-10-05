from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from tenancy.context import require_membership
from tenancy.models import Membership

from .models import Notification
from .serializers import NotificationSerializer


NOTIFICATION_ROLES = [
    Membership.Role.DOCTOR,
    Membership.Role.NURSE,
]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_membership(self):
        return require_membership(
            user=self.request.user,
            practice_id=self.request.headers.get("X-Practice-ID"),
            roles=NOTIFICATION_ROLES,
        )

    def get_queryset(self):
        membership = self.get_membership()

        return Notification.objects.filter(
            practice=membership.practice,
            recipient=self.request.user,
        ).select_related(
            "practice",
            "recipient",
            "appointment",
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="mark-read",
    )
    def mark_read(self, request, pk=None):
        notification = self.get_object()

        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(
                update_fields=[
                    "read_at",
                ]
            )

        serializer = self.get_serializer(notification)

        return Response(serializer.data)
