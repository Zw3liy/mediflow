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

## Account lifecycle and MFA

Production now defaults to `MEDIFLOW_ADMIN_MFA_REQUIRED=True`. Every owner,
reception user, staff user and superuser is gated by MFA on portal, admin and API
routes. At first sign-in, use an authenticator app with the displayed private
setup key, confirm the current password and a code, then save the ten single-use
recovery codes separately. Codes are hashed in the database; TOTP devices use
Django-OTP's replay checks and throttling. Protect database access and backups,
since authenticator shared keys necessarily reside in the database.

Do not enable a real-patient release before administrators are enrolled. Enrol
first through a private connection with each legitimate administrator present.
If both phone and recovery codes are lost, verify the person's identity using
the practice's documented process before a trusted server operator removes that
user's TOTP device. Never implement a public email-only MFA bypass. Authenticator
code recovery does not remove MFA or change passwords.

Reception can create doctor and patient accounts. Use email invitations for
production: the user chooses their own password through a random, single-use,
24-hour link. Initial passwords remain available for controlled onboarding while
SMTP is being configured. Invitations are invalidated by resend and disabling
practice access. Invite/reset requests have persistent rate limits. Password
reset links expire after one hour and changing a password invalidates other
Django sessions. Reset does not bypass administrator MFA.

Configure `.env` with a permanent `MEDIFLOW_PUBLIC_URL`, `EMAIL_HOST`, port,
SMTP username, a dedicated SMTP token, `DEFAULT_FROM_EMAIL` and
`MEDIFLOW_EMAIL_ENABLED=True`. Proton SMTP uses `smtp.protonmail.ch:587` with
STARTTLS, a paid plan and a custom domain; a personal proton.me mailbox alone
is not an application mail service. Never enter the Proton mailbox password.
Start `account-email` under the automation profile. Check delivery at the actual
recipient and spam folder before launch. Queue contents include secret account
links, so limit DB access; message bodies are erased on successful delivery and
expired tasks removed. Delivery can duplicate a message if SMTP succeeds but the
DB commit fails; links remain single-use. Invalid or unknown reset emails receive
the same response. Shared email addresses are excluded from recovery; establish
individual addresses for every account.

Manage accounts from the reception dashboard. Disabling a membership removes its
practice access immediately without deleting care records or other memberships.
Only doctor/patient memberships can be changed here. No staff/superuser, owner or
reception privileges can be granted through these controls.

## Permanent server and HTTPS

Buy/register the practice's domain and provision an always-on Linux server. Decide
with the practice where data may be hosted, who operates the server and the
required recovery objectives before purchasing. The current WSL laptop/quick
tunnel is a demo environment, not the production target.

Point the domain's DNS to the server. Permit only HTTPS/HTTP for certificate
issuance and tightly restricted SSH; PostgreSQL and app ports remain private.
Set `MEDIFLOW_DOMAIN`, `MEDIFLOW_PUBLIC_URL`, exact allowed hosts and CSRF origins.
Run with the additional `compose.production.yaml` file to enable Caddy's automatic
HTTPS. Persist its certificate volumes. Caddy overwrites the forwarded scheme
and does not enable access logging of clinical URLs. Protect `/admin/` further
with a VPN/identity-aware access layer. Server admin access needs MFA too.

```bash
docker compose -f compose.yaml -f compose.production.yaml config --quiet
docker compose -f compose.yaml -f compose.production.yaml --profile automation up -d --build
```

Validate actual TLS, redirects, cookie flags and sign-in/out before opening access.
`Referrer-Policy: same-origin` is intentional: `no-referrer` can cause browsers to
send `Origin: null` on form submissions and break CSRF verification. Never trust
`null` origins or disable CSRF to work around this.

## Offsite encryption and full recovery

`compose.offsite.yaml` uses Restic client-side encryption for backup copies.
Choose a private repository on separate infrastructure, scoped credentials and
an encryption password stored separately from this server. Losing that password
makes the backups unrecoverable. Put credentials in `.env.offsite` with mode 600;
never commit it. The repository must be initialized explicitly once, then start
the offsite profile. A destination account, bucket and credentials are not
created by this repository.

```bash
docker compose -f compose.yaml -f compose.offsite.yaml --profile offsite run --rm --entrypoint restic offsite-backup init
docker compose -f compose.yaml -f compose.offsite.yaml --profile offsite up -d offsite-backup
```

After confirming a snapshot in the remote repository and testing a restore, set
`MEDIFLOW_OFFSITE_BACKUP_REQUIRED=True`. The success marker is useful monitoring
evidence, not a substitute for a recovery drill. Run Restic `check` and restore a
snapshot into isolated storage on another machine. Run `verify_restore.sh` on its
backup set in an isolated PostgreSQL environment; it restores the database and
extracts the documents to temporary storage. Verify a test patient's prescription
can actually be opened from that recovered system. Record dates and outcomes.
Do not overwrite live data during a drill. Keep the approved recovery password
and MFA recovery arrangements available to authorised emergency operators.

Local backups are sequential DB dump plus document archive, so use a coordinated
maintenance window/snapshot for strict cross-component consistency. Review
Restic snapshot retention and storage lifecycle against the approved clinical
retention policy; automatic remote pruning is deliberately not enabled.

## Monitoring and release gate

Start `operations-monitor` and `account-email` along with scanner/maintenance/
backup-scheduler. The monitor checks DB availability, scanner heartbeat, pending
documents, overdue email tasks, local backup age and the optional offsite marker.
Set `MEDIFLOW_OPERATIONS_EMAIL`; alerts contain no patient details. Application
server errors queue generic alerts. Simulate a failed backup/scanner and a test
server error, verify alert delivery, then restore the service.

Configure an independent uptime service to check the public `/health/ready/`
endpoint. This must run outside the server, because a stopped server cannot
send its own alerts. Test outage/recovery notifications before setting
`MEDIFLOW_EXTERNAL_MONITOR_CONFIGURED=True`. Configure host disk/memory monitoring
and protected log retention separately. File permissions and disk encryption are
part of the host setup.

```bash
docker compose exec -T operations-monitor python manage.py check_operations
docker compose exec -T operations-monitor python manage.py check_release_readiness
```

The release gate fails for temporary URLs, incomplete SMTP, missing administrator
MFA, missing operator/privacy/retention details, missing monitoring and unverified
recent backup evidence. Passing it does not replace clinical acceptance or privacy
review. Keep production CI required and prohibit force pushes to main in GitHub
branch settings. GitHub admin access is needed to configure those rules.

## Privacy and operational acceptance

The public privacy page is an initial technical notice. The practice must approve
its content, operator name, privacy contact and `MEDIFLOW_RETENTION_NOTICE` before
release. Fill in a record-category retention schedule, access/correction request
process, consent purposes, incident contacts, provider agreements, storage regions
and transfer decisions. Do not invent consent or blanket-delete clinical records.
Review against the practice's obligations with its Information Officer/adviser.

Store the approved policy version with consent records, train staff to verify the
patient before account linking, prohibit shared logins and record who may disable
accounts. Account disabling preserves records. Document the clinical downtime
procedure and a recovery drill. Test with synthetic patients only until approval.

Release acceptance must cover: reception request/intake/approval; doctor only
sees their queue; doctor approval/call generates updates only for the linked
patient; second patient and second practice cannot see records or documents;
released/clean PDFs download while pending/blocked PDFs do not; signup, MFA,
password recovery, logout, expired links and disabled access all behave correctly.
The mobile PR is still separate and requires its own integration/release review.
