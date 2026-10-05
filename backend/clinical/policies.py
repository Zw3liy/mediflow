from rest_framework.exceptions import PermissionDenied

from tenancy.models import Membership


def require_patient_access(
    *,
    membership,
    patient,
    clinical=False,
):
    if membership.practice_id != patient.practice_id:
        raise PermissionDenied(
            "Patient access denied."
        )

    if not membership.active:
        raise PermissionDenied(
            "Patient access denied."
        )

    if membership.role == Membership.Role.PATIENT:
        if patient.portal_user_id != membership.user_id:
            raise PermissionDenied(
                "Patient access denied."
            )

        return

    if clinical and membership.role not in {
        Membership.Role.DOCTOR,
        Membership.Role.NURSE,
    }:
        raise PermissionDenied(
            "Clinical access denied."
        )
