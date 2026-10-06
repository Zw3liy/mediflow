import hashlib
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from tenancy.models import Membership
from .models import MobileSession

WORKSPACES = {"reception": ["owner", "reception"], "doctor": ["doctor"], "patient": ["patient"]}


class MobileTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != b"bearer":
            return None
        if len(parts) != 2 or len(parts[1]) > 256:
            raise AuthenticationFailed("Invalid mobile session.")
        hashed = hashlib.sha256(parts[1]).hexdigest()
        session = MobileSession.objects.select_related("user", "practice").filter(
            token_hash=hashed, revoked_at__isnull=True, expires_at__gt=timezone.now(), user__is_active=True,
            practice__active=True).first()
        if session is None:
            raise AuthenticationFailed("Your session has expired. Sign in again.")
        membership = Membership.objects.filter(user=session.user, practice=session.practice, active=True,
            role__in=WORKSPACES.get(session.workspace, [])).first()
        if membership:
            session.current_role = membership.role
        elif session.user.is_superuser and session.workspace == "reception":
            session.current_role = "owner"
        else:
            raise AuthenticationFailed("Your practice access is no longer active.")
        return session.user, session

    def authenticate_header(self, request):
        return "Bearer"
