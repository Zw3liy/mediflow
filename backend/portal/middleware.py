from django.utils import timezone


class PortalTimezoneMiddleware:
    """Store UTC timestamps; use explicitly labelled South African times in the portal."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith("/app/"):
            with timezone.override("Africa/Johannesburg"):
                return self.get_response(request)
        return self.get_response(request)
