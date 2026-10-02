from rest_framework.routers import DefaultRouter

from .views import AppointmentViewSet, ServiceViewSet


router = DefaultRouter()
router.register("services", ServiceViewSet, basename="service")
router.register(
    "appointments",
    AppointmentViewSet,
    basename="appointment",
)

urlpatterns = router.urls
