from django.contrib import admin
from django.urls import include, path


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("patients.urls")),
    path("api/", include("scheduling.urls")),
    path("api/", include("notifications.urls")),
    path("api/", include("clinical.urls")),
    path("api/", include("documents.urls")),
    path("api-auth/", include("rest_framework.urls")),
    path("api/payments/", include("payments.urls",)),
]
