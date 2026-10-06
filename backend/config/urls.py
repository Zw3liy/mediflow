from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from .health import live, ready


urlpatterns = [
    path("", RedirectView.as_view(url="/app/", permanent=False)),
    path("app/", include("portal.urls")),
    path("health/live/", live, name="health-live"),
    path("health/ready/", ready, name="health-ready"),
    path("admin/", admin.site.urls),
    path("api/", include("patients.urls")),
    path("api/", include("scheduling.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("clinical.urls")),
    path("api/", include("documents.urls")),
    path("api-auth/", include("rest_framework.urls")),
    path("api/payments/", include("payments.urls",)),
]
