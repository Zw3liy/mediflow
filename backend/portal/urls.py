from django.contrib.auth import views as auth_views
from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="portal-home"),
    path("login/", auth_views.LoginView.as_view(template_name="portal/login.html", redirect_authenticated_user=True), name="portal-login"),
    path("logout/", auth_views.LogoutView.as_view(), name="portal-logout"),
    path("new/<str:kind>/", views.form_view, name="portal-form"),
    path("appointments/<int:pk>/<str:operation>/", views.appointment_action, name="portal-appointment-action"),
    path("prescriptions/<int:pk>/issue/", views.issue, name="portal-issue"),
    path("documents/<uuid:pk>/download/", views.document_download, name="portal-download"),
    path("<str:workspace>/", views.dashboard, name="portal-dashboard"),
]
