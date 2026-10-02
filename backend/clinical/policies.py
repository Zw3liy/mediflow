from rest_framework.exceptions import PermissionDenied
def require_patient_access(
*, membership, patient, clinical=False
):
if membership.practice_id != patient.practice_id:
raise PermissionDenied("Patient␣access␣denied.")
if not membership.active:
raise PermissionDenied("Patient␣access␣denied.")
if membership.role == "patient":
if patient.portal_user_id != membership.user_id:
raise PermissionDenied("Patient␣access␣denied.")
return
if clinical and membership.role not in {"doctor", "nurse"}:
raise PermissionDenied("Clinical␣access␣denied.")
patient = get_object_or_404(
Patient.objects.filter(practice=membership.practice),
pk=patient_id)
require_patient_access(
membership=membership,
patient=patient,
clinical=True)
