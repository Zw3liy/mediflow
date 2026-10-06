from datetime import timedelta

from django.conf import settings
from django.contrib.auth import logout
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.utils.cache import patch_cache_control

from .models import LoginAttemptBucket


def bucket_key(kind, value):
    return salted_hmac("mediflow.login." + kind, value, algorithm="sha256").hexdigest()


class SecurityGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        now = timezone.now()
        if request.user.is_authenticated:
            last_seen = request.session.get("security_last_seen", now.timestamp())
            started_at = request.session.get("security_session_started", now.timestamp())
            if (now.timestamp() - last_seen > settings.SESSION_IDLE_TIMEOUT
                    or now.timestamp() - started_at >= settings.SESSION_ABSOLUTE_TIMEOUT):
                logout(request)
            else:
                if "security_session_started" not in request.session:
                    request.session["security_session_started"] = now.timestamp()
                if now.timestamp() - last_seen >= 60 or "security_last_seen" not in request.session:
                    request.session["security_last_seen"] = now.timestamp()
        was_authenticated = request.user.is_authenticated
        response = self.get_response(request)
        if (getattr(request, "security_login_account", None) and request.user.is_authenticated
                and bucket_key("account", request.user.get_username().strip().casefold()[:256]) == request.security_login_account
                and response.status_code in (302, 303)):
            LoginAttemptBucket.objects.filter(key=request.security_login_account).delete()
            if not was_authenticated:
                request.session["security_session_started"] = now.timestamp()
                request.session["security_last_seen"] = now.timestamp()
        if request.path.startswith(("/app/", "/admin/", "/api/")):
            patch_cache_control(response, private=True, no_store=True)
            response["Referrer-Policy"] = "same-origin"
            response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.path.startswith("/app/"):
            response["Content-Security-Policy"] = (
                "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Applies before password hashing, across reception/doctor/patient/admin.
        if request.method != "POST" or not (
            request.path in ("/admin/login/", "/api-auth/login/") or
            request.path.startswith(("/app/login/", "/app/password/", "/app/invite/", "/app/security/mfa/"))
        ):
            return None
        username = request.POST.get("username") or request.POST.get("email") or (str(request.user.pk) if request.user.is_authenticated else request.path)
        account = bucket_key("account", username.strip().casefold()[:256])
        # Never trust client-supplied X-Forwarded-For. A proxy may share this bucket.
        address = bucket_key("address", request.META.get("REMOTE_ADDR", "unknown"))
        now = timezone.now()
        limits = sorted([(account, settings.LOGIN_ACCOUNT_LIMIT), (address, settings.LOGIN_ADDRESS_LIMIT)])
        with transaction.atomic():
            buckets = []
            for key, limit in limits:
                bucket, _ = LoginAttemptBucket.objects.get_or_create(key=key, defaults={"started_at": now})
                bucket = LoginAttemptBucket.objects.select_for_update().get(pk=bucket.pk)
                if now - bucket.started_at >= timedelta(seconds=settings.LOGIN_ATTEMPT_WINDOW):
                    bucket.started_at, bucket.attempts = now, 0
                buckets.append((bucket, limit))
            if any(bucket.attempts >= limit for bucket, limit in buckets):
                response = HttpResponse("Too many sign-in attempts. Try again later.", status=429, content_type="text/plain")
                retry = max(1, max(int(settings.LOGIN_ATTEMPT_WINDOW - (now - b.started_at).total_seconds()) for b, limit in buckets if b.attempts >= limit))
                response["Retry-After"] = str(retry)
                return response
            for bucket, _ in buckets:
                bucket.attempts += 1
                bucket.save(update_fields=["started_at", "attempts"])
        request.security_login_account = account
        return None
