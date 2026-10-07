from django.contrib.auth import views as auth_views
from django.urls import path
from . import views, scans
from .auth import WorkspaceLoginView
from securityguard import views as security_views
from securityguard.forms import QueuedPasswordResetForm

urlpatterns = [
    path("scans/", scans.scan_page, name="portal-scans"),
    path("scans/api/", scans.BrowserDocumentScans.as_view()),
    path("scans/api/<uuid:pk>/", scans.BrowserDocumentReview.as_view()),
    path("scans/api/<uuid:pk>/download/<str:kind>/", scans.BrowserDocumentDownload.as_view()),
    path("privacy/", views.privacy, name="portal-privacy"),
    path("security/mfa/", security_views.mfa, name="portal-mfa"),
    path("security/mfa/setup/", security_views.mfa_setup, name="portal-mfa-setup"),
    path("security/password/", auth_views.PasswordChangeView.as_view(template_name="portal/security_form.html", success_url="/app/"), name="portal-password-change"),
    path("password/reset/", auth_views.PasswordResetView.as_view(form_class=QueuedPasswordResetForm, template_name="portal/security_form.html", success_url="/app/password/reset/done/"), name="portal-password-reset"),
    path("password/reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="portal/reset_done.html"), name="portal-reset-done"),
    path("password/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="portal/security_form.html", success_url="/app/password/reset/complete/"), name="portal-reset-confirm"),
    path("password/reset/complete/", auth_views.PasswordResetCompleteView.as_view(template_name="portal/reset_complete.html"), name="portal-reset-complete"),
    path("invite/<str:token>/", security_views.accept_invitation, name="portal-invitation"),
    path("accounts/", views.accounts, name="portal-accounts"),
    path("accounts/<int:pk>/<str:operation>/", views.account_action, name="portal-account-action"),
    path("", views.home, name="portal-home"),
    path("login/", views.login_choices, name="portal-login"),
    path("login/<str:workspace>/", WorkspaceLoginView.as_view(), name="portal-workspace-login"),
    path("notifications/", views.notification_feed, name="portal-notification-feed"),
    path("notifications/<int:pk>/read/", views.notification_read, name="portal-notification-read"),
    path("appointments/<int:pk>/intake/", views.intake, name="portal-intake"),
    path("logout/", auth_views.LogoutView.as_view(), name="portal-logout"),
    path("patients/<uuid:pk>/account/", views.patient_account, name="portal-patient-account"),
    path("accounts/new/<str:account_role>/", views.create_account, name="portal-create-account"),
    path("new/<str:kind>/", views.form_view, name="portal-form"),
    path("appointments/<int:pk>/<str:operation>/", views.appointment_action, name="portal-appointment-action"),
    path("prescriptions/<int:pk>/issue/", views.issue, name="portal-issue"),
    path("documents/<uuid:pk>/download/", views.document_download, name="portal-download"),
    path("<str:workspace>/", views.dashboard, name="portal-dashboard"),
]
