from django.contrib.auth import views as auth_views
from django.urls import path
from . import views
from .auth import WorkspaceLoginView

urlpatterns = [
    path("", views.home, name="portal-home"),
    path("login/", views.login_choices, name="portal-login"),
    path("login/<str:workspace>/", WorkspaceLoginView.as_view(), name="portal-workspace-login"),
    path("notifications/", views.notification_feed, name="portal-notification-feed"),
    path("notifications/<int:pk>/read/", views.notification_read, name="portal-notification-read"),
    path("appointments/<int:pk>/intake/", views.intake, name="portal-intake"),
    path("logout/", auth_views.LogoutView.as_view(), name="portal-logout"),
    path("patients/<uuid:pk>/account/", views.patient_account, name="portal-patient-account"),
    path("new/<str:kind>/", views.form_view, name="portal-form"),
    path("appointments/<int:pk>/<str:operation>/", views.appointment_action, name="portal-appointment-action"),
    path("prescriptions/<int:pk>/issue/", views.issue, name="portal-issue"),
    path("documents/<uuid:pk>/download/", views.document_download, name="portal-download"),
    path("<str:workspace>/", views.dashboard, name="portal-dashboard"),
]
