from django.urls import path
from . import views

urlpatterns = [
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
