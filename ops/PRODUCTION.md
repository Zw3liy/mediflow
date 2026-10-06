# MediFlow production security and release checklist

This release hardens the web application. A green CI run confirms the checked-in
code, not the security or uptime of a particular Ubuntu installation. Do not
declare a clinical deployment ready until the runtime steps below are recorded.

## Configuration and rollout

1. Confirm a stable practice HTTPS hostname and a trusted reverse proxy/tunnel.
   Do not use a changing Quick Tunnel hostname for a permanent deployment.
2. Back up the current database and private documents before upgrading. Retain
   the prior image/commit and environment configuration for rollback. Never run
   `docker compose down --volumes` on the live server.
3. Update `.env` using `.env.example` as the list of keys, preserving existing
   credentials. Set `DJANGO_PRODUCTION=True`, `DJANGO_DEBUG=False`, explicit hosts
   including the real hostname and loopback for health checks, explicit HTTPS
   CSRF origins, HTTPS redirects and an initial HSTS lifetime of 300 seconds.
   Replace all example values. Generate unique random production secrets (at
   least 50 characters for Django and 20 for PostgreSQL); do not paste them into
   chat or commit them. Changing a Postgres environment password does NOT change
   the password in an initialized database: rotate the database role and matching
   clients together in a maintenance window. Rotating the Django secret signs
   out users and invalidates existing signed download links.
4. Run `docker compose config --quiet`, then build the candidate web image.
   Validate it with `docker compose run --rm web python manage.py check_production`.
   Production-mode Django also checks configuration during startup, including
   direct Gunicorn entrypoints. The Compose startup additionally treats Django
   deployment warnings as errors. Missing secrets, SQLite, wildcard hosts,
   HTTP-only configuration and unsafe cookie settings cause startup to fail.
5. In the planned deployment window, run `docker compose up -d --build web`.
   Startup applies the additive login-attempt migration and collects static files.
   Enable `docker compose --profile automation up -d --build backup-scheduler maintenance document-scanner`.
   Verify web health and inspect recent logs without disclosing credentials.
6. Keep HSTS subdomain/preload options off until every affected hostname is
   verified. Increase the HSTS duration only after HTTPS and renewal are proven.
   Django's W005/W021 opt-in advisories are explicitly silenced for this staged
   rollout; all other deployment warnings still fail the production command.

CI explicitly uses `DJANGO_PRODUCTION=False` for its disposable HTTP smoke test;
it separately executes the strict production startup/configuration check. A local
HTTP demo can use that non-production mode, but this is not a production workaround.

## Network and server controls

- Keep Gunicorn on the loopback-published port. Only the TLS proxy/tunnel should
  reach it; the proxy must replace/sanitize `X-Forwarded-Proto`. Django trusts that
  header to recognize HTTPS. Do not expose Gunicorn directly to the internet.
- Keep PostgreSQL and document storage private. Default Compose starts neither
  the currently unused Redis nor MinIO; these are behind `optional-storage`.
- Restrict administrative access with VPN/private networking or an identity-aware
  proxy with MFA. Staff MFA is not implemented inside Django by this change.
- Apply host updates; restrict SSH to authorized keys and required networks;
  verify the firewall, disk encryption, clock synchronization and reboot recovery.
  Take care with Docker-published ports when checking firewall rules.
- Use separate staff accounts, least-privilege memberships and individual patient
  accounts. Keep superuser credentials for administration only. Verify account
  recovery/offboarding procedures before using real clinical records.
- Set proxy request limits consistent with the supported PDF upload limit of
  10 MiB plus multipart overhead. Django limits ordinary in-memory request data
  to 2 MiB. Preserve the existing file-size and malware-scan checks.
- Monitor HTTPS expiry, readiness failures, failed backups, disk usage, repeated
  sign-in failures and container restarts. Limit log retention and avoid tokens,
  passwords, symptoms or other unnecessary patient details in operational logs.

## Application changes and operational effects

- Web login limits are stored in PostgreSQL across workers: five attempts per
  normalized username and 100 attempts per direct peer address in 15 minutes.
  Successful login resets its own account bucket, not the address bucket.
  A limited login returns 429 with Retry-After. Identifiers are HMAC digests.
  Username limits apply across all three workspaces and Django admin, so switching
  pages does not bypass them. Account limits can temporarily deny a victim login;
  this tradeoff is bounded by the window. Add edge abuse controls for internet use.
- Forwarded client addresses are deliberately ignored. With a loopback proxy,
  users share its direct-peer address bucket. Test legitimate practice login
  traffic and configure trusted edge rate limits before launch. Do not blindly
  switch to trusting arbitrary X-Forwarded-For headers.
- HTTP Basic authentication is disabled for browser APIs. Integrations using it
  must migrate; browser APIs use CSRF-protected sessions. This change does not
  alter the separate native bearer-token API in the currently open mobile PR.
- Browser sessions expire after eight hours and on browser close, with a 30-minute
  idle limit. Background portal polling counts as activity; a tab left polling
  can remain active until the absolute session expiry. Do not treat this as a
  screen-lock substitute on shared reception/clinical computers.
- Portal responses receive a restrictive Content Security Policy. Portal, admin
  and API responses are private/no-store with no-referrer and permissions headers.
  Verify screen interactions and document downloads after deployment. Django admin
  keeps its own asset behavior; the portal CSP is not imposed on its inline assets.
- New/changed passwords validated by Django require at least 12 characters.
  Existing passwords are not automatically rotated. Direct programmatic account
  creation must explicitly use Django password validation; create_user does not.
- Production cannot create sandbox payment checkout links; the endpoint returns
  503 until a real payment gateway is implemented. Do not claim live online payment
  support. Existing appointment approval workflows still work.
- The configured private document-storage root is now respected. Backups use
  restrictive creation permissions. Restore verification stops on SQL restore
  errors. The web and maintenance containers drop Linux capabilities and cannot
  acquire new privileges. This does not replace host protection.
- The automation profile scans pending PDFs every 15 seconds. Scanning failures
  keep documents unavailable; monitor worker exits and failed scan statuses.
  A clean scan still requires staff release before patient downloads. CI starts
  the scanner and exercises backup plus restoration to a separate temporary DB.

## Backup and recovery evidence

Run from the repository folder on the Ubuntu server:

```bash
docker compose --profile operations run --rm backup
docker compose --profile operations run --rm restore-verify
docker compose --profile automation ps
```

The verification creates and drops a separate temporary database; it does not
overwrite the live database. Check the output and backup timestamp. The database
role needs permission to create that temporary database for this verification.
For a full recovery drill, use an isolated machine to restore the database and
documents and confirm a released PDF's checksum and access restrictions. Database
and document backups are taken sequentially; use a controlled maintenance window
or a coordinated snapshot strategy for a strictly consistent pair.

These are local backups, not encrypted offsite disaster recovery. Implement an
encrypted, access-controlled offsite copy, establish retention and recovery time
targets, and alert on failed/stale backups. Keep encryption keys recoverable in a
separate secure location. Record a successful isolated recovery before launch.

## Required live acceptance test (use test records)

1. Confirm HTTP redirects to HTTPS; login/session cookies carry Secure and
   HttpOnly as applicable; HSTS and portal CSP are present.
2. Patient A requests a visit. Reception records symptoms/BP and approves it.
3. Assigned Doctor A receives the correct intake, approves and calls the patient.
4. Patient A receives the personal update. Patient B cannot read that appointment,
   notification or document by changing identifiers. Doctor B cannot approve it.
5. Complete the consultation and verify that the next-patient queue advances.
6. Create/review/issue a prescription. An unscanned, infected or unreleased file
   cannot be downloaded; a clean released file is available only to its patient.
7. Verify logout, idle expiry, role revocation, CSRF rejection and login rate limit.
8. Confirm automated backups, recovery drill, certificate renewal and restart
   recovery. Record exact deployed commit, operator, date and test results.

Outstanding infrastructure/configuration evidence includes the real HTTPS address,
edge/admin access protection, production secrets, backups/offsite recovery,
monitoring and device/network acceptance. This checklist cannot certify these
without access to the running installation. OS push/SMS/email delivery is also
not verified by web CI.

Official guidance: https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/
and https://docs.djangoproject.com/en/5.2/ref/settings/#secure-proxy-ssl-header
