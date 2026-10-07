"""CSRF-protected browser adapters for the shared document review workflow."""
import base64
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied

from mobile_api.document_scans import MobileDocumentScans, MobileDocumentScanReview, MobileDocumentScanDownload
from .views import scope, ROLE_PATHS


class BrowserScanMixin:
    authentication_classes = [SessionAuthentication]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        practice, role, _ = scope(request, ['owner', 'reception'])
        if practice is None:
            raise PermissionDenied('An active practice is required.')
        request.auth = SimpleNamespace(practice=practice, current_role=role)


class BrowserDocumentScans(BrowserScanMixin, MobileDocumentScans):
    pass


class BrowserDocumentReview(BrowserScanMixin, MobileDocumentScanReview):
    pass


class BrowserDocumentDownload(BrowserScanMixin, MobileDocumentScanDownload):
    def get(self, request, pk, kind):
        result = super().get(request, pk, kind)
        response = HttpResponse(base64.b64decode(result.data['base64']), content_type=result.data['content_type'])
        response['Content-Disposition'] = 'attachment; filename="patient-document.pdf"' if kind == 'pdf' else 'inline'
        return response


@never_cache
@login_required
@require_GET
def scan_page(request):
    practice, role, practices = scope(request, ['owner', 'reception'])
    if practice is None:
        return render(request, 'portal/no_access.html')
    return render(request, 'portal/scans.html', {'practice': practice, 'role': role, 'practices': practices,
        'workspace': ROLE_PATHS[role], 'title': 'Scan patient document'})
