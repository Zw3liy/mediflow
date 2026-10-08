from django.urls import path
from . import views
from .document_scans import MobileDocumentScans, MobileDocumentScanReview, MobileDocumentScanDownload

from .health import HealthPatients, HealthEntries, HealthEntryEdit

urlpatterns = [
    path("health/patients/", HealthPatients.as_view()),
    path("health/<uuid:patient_id>/", HealthEntries.as_view()),
    path("health/<uuid:patient_id>/<int:pk>/", HealthEntryEdit.as_view()),
    path("document-scans/", MobileDocumentScans.as_view()),
    path("document-scans/<uuid:pk>/", MobileDocumentScanReview.as_view()),
    path("document-scans/<uuid:pk>/download/<str:kind>/", MobileDocumentScanDownload.as_view()),
    path("login/", views.MobileLogin.as_view()),
    path("logout/", views.MobileLogout.as_view()),
    path("dashboard/", views.MobileDashboard.as_view()),
    path("booking-options/", views.MobileBookingOptions.as_view()),
    path("appointments/", views.MobileBooking.as_view()),
    path("appointments/<int:pk>/<str:operation>/", views.MobileAppointmentAction.as_view()),
    path("notifications/<int:pk>/read/", views.MobileNotificationRead.as_view()),
    path("devices/", views.MobileDevices.as_view()),
    path("prescriptions/", views.MobilePrescriptionCreate.as_view()),
    path("prescriptions/<int:pk>/issue/", views.MobilePrescriptionIssue.as_view()),
    path("patients/", views.MobilePatientCreate.as_view()),
]
