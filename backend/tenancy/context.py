from django.core.exceptions import PermissionDenied

from .models import Membership


def require_membership(*, user, practice_id, roles=None):
    if not user or not user.is_authenticated:
        raise PermissionDenied("Authentication required.")

    if not practice_id:
        raise PermissionDenied("Practice ID required.")

    query = Membership.objects.select_related("practice").filter(
        user=user,
        practice_id=practice_id,
        active=True,
        practice__active=True,
    )

    if roles:
        query = query.filter(role__in=roles)

    membership = query.first()

    if not membership:
        raise PermissionDenied("Practice access denied.")

    return membership
