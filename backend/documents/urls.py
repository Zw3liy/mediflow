from rest_framework.routers import DefaultRouter

from .views import PrescriptionDocumentViewSet


router = DefaultRouter()
router.register(
    "prescription-documents",
    PrescriptionDocumentViewSet,
    basename="prescription-document",
)

urlpatterns = router.urls
