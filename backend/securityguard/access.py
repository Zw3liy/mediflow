from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from tenancy.models import Membership


class MFAAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        if not user.is_authenticated or not settings.ADMIN_MFA_REQUIRED:
            return None
        # Every authenticated route is gated, including direct API and Django admin.
        privileged = user.is_staff or user.is_superuser or Membership.objects.filter(
            user=user, active=True, practice__active=True, role__in=['owner', 'reception']).exists()
        safe_paths = ('/app/security/mfa/', '/app/security/password/', '/app/logout/')
        if privileged and not user.is_verified() and not request.path.startswith(safe_paths):
            if request.path.startswith('/api/'):
                return JsonResponse({'detail': 'Administrator MFA verification required.'}, status=403)
            return redirect('/app/security/mfa/')
        return None

    def __call__(self, request):
        return self.get_response(request)
