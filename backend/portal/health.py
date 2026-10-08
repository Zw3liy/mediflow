from types import SimpleNamespace
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied
from mobile_api.health import HealthPatients, HealthEntries, HealthEntryEdit
from .views import scope, ROLE_PATHS
class BrowserHealth:
    authentication_classes = [SessionAuthentication]
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        practice, role, _ = scope(request, ["owner", "doctor", "reception", "patient"])
        if not practice: raise PermissionDenied("An active practice is required.")
        request.auth = SimpleNamespace(practice=practice, current_role=role)
class BrowserPatients(BrowserHealth, HealthPatients): pass
class BrowserEntries(BrowserHealth, HealthEntries): pass
class BrowserEdit(BrowserHealth, HealthEntryEdit): pass
@never_cache
@login_required
def page(request):
    practice, role, practices = scope(request, ["owner", "doctor", "reception", "patient"])
    if not practice: return render(request, "portal/no_access.html")
    return render(request, "portal/health.html", {"practice":practice,"role":role,"practices":practices,"workspace":ROLE_PATHS[role],"title":"My Health"})
