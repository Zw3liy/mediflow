def configuration_errors(settings):
    failures = []
    if settings.DEBUG:
        failures.append("DEBUG must be False")
    secret = settings.SECRET_KEY
    if len(secret) < 50 or len(set(secret)) < 5 or any(value in secret.lower() for value in ("django-insecure", "replace", "development", "ci-only")):
        failures.append("Use a unique random production secret with at least 50 characters")
    if not settings.ALLOWED_HOSTS or any(host.startswith(".") or "*" in host for host in settings.ALLOWED_HOSTS):
        failures.append("Configure explicit ALLOWED_HOSTS without wildcards")
    if not any(host not in ("localhost", "127.0.0.1", "[::1]") for host in settings.ALLOWED_HOSTS):
        failures.append("Configure the actual practice hostname")
    if not settings.SECURE_SSL_REDIRECT:
        failures.append("HTTPS redirects must be enabled")
    if settings.SECURE_HSTS_SECONDS < 300:
        failures.append("Enable HSTS after verifying HTTPS (at least 300 seconds)")
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
        failures.append("Production requires PostgreSQL")
    password = settings.DATABASES["default"].get("PASSWORD", "")
    if len(password) < 20 or any(value in password.lower() for value in ("replace", "password", "changeme")):
        failures.append("Use a unique strong PostgreSQL password (at least 20 characters)")
    if any(not origin.startswith("https://") or "*" in origin for origin in settings.CSRF_TRUSTED_ORIGINS):
        failures.append("CSRF trusted origins must be explicit HTTPS origins")
    if not settings.SESSION_COOKIE_SECURE or not settings.CSRF_COOKIE_SECURE:
        failures.append("Secure session and CSRF cookies are required")
    return failures
