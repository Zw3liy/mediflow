# MediFlow for Android and iPhone

Native Expo SDK 57 / React Native application with Expo Router. The installed app uses native controls and authenticated Django APIs, not a WebView or browser wrapper. Android and iOS share the same screens and business workflow.

The sign-in screen offers **Reception**, **Doctor** and **Patient**. Permissions are checked by the server on every request. Patients request their own visits and receive personal updates; reception approves requests and records symptoms and optional blood pressure; assigned doctors review the intake, approve the visit, notify the patient when ready, open consultations and review/issue prescriptions. All displayed visit times are South African time (SAST).

## Run and check

Use Node 22.13 or newer and an Expo account for EAS builds.

```bash
cd mobile
npm ci
cp .env.example .env
# Set EXPO_PUBLIC_API_URL to the practice's HTTPS origin, without /api/.
npm run typecheck
npm run lint
npm run export:native
```

If the build has no API URL, the native login screen asks for the practice HTTPS address. A changing Quick Tunnel address can be entered for testing; use a stable HTTPS hostname for deployment. The Ubuntu PC, Docker and the tunnel must remain running for the app to reach the server. Patient accounts still need an active patient membership and their patient record linked to that account.

## Installable builds

The **Android installable preview** GitHub workflow builds an arm64 standalone APK with embedded JavaScript and uploads `mediflow-android-preview`. Download its ZIP, extract the APK and install it on an Android phone. This preview uses the generated Android debug signing key even though the bundle is built in release mode: it is a test installer, not a production store release. No development server is needed. Rebuilt previews may require uninstalling a previous preview because their signing key can change. Do not use this artifact for sensitive clinical data or production distribution.

For signed, managed Android and iPhone builds:

```bash
npx eas-cli@latest login
npx eas-cli@latest build:configure
# Set EXPO_PUBLIC_EAS_PROJECT_ID to your project's UUID before building.
# Configure EXPO_PUBLIC_API_URL in the EAS build environment.
npx eas-cli@latest build --platform android --profile preview
npx eas-cli@latest device:create
npx eas-cli@latest build --platform ios --profile preview
```

The Android preview is an APK. The iPhone preview needs Apple Developer signing and registered devices; install using the EAS internal distribution link. For App Store/TestFlight and Google Play builds, use `--profile production` and configure the relevant developer/store accounts. An iOS simulator build (`--platform ios --profile simulator`) runs on a Mac simulator and does not install on a physical iPhone. Never commit signing credentials, private keys or Google service files.

## Phone notifications

In-app personal updates work without push credentials and refresh while the app is active. Background/lock-screen alerts require an EAS project, FCM v1 credentials for Android and APNs credentials for iOS. Set the build's `EXPO_PUBLIC_EAS_PROJECT_ID`, and configure Android's `GOOGLE_SERVICES_JSON` as an EAS secret file environment variable. Each user enables notifications in the native Updates tab on their physical device.

On the server set `MOBILE_PUSH_ENABLED=True` and `EXPO_ACCESS_TOKEN` to an Expo access token with push security enabled for the project. Then start the optional worker:

```bash
docker compose --profile mobile-push up -d --build push-scheduler
```

Alerts say “MediFlow update” and ask the recipient to open their personal inbox. Symptoms, blood pressure and patient names are not placed on the lock screen. The server queues deliveries, checks current account/record ownership before sending, and retries temporary provider failures. A saved `sent` ticket means provider acceptance, not guaranteed arrival on the device; push receipts are not yet monitored. Validate real device delivery before relying on phone alerts.

Sessions expire after seven days. Only a random bearer token is stored in the platform secure store; passwords are not saved. Signing out revokes the server session and its device registration, and therefore currently requires a reachable server. APIs return private, non-cacheable responses. App data remains in memory while in use.

## Dependency review

The lockfile overrides the navigation dependency `decode-uri-component` to patched 0.5.0 (GHSA-vcc3-ghjq-m6fr). Its upstream algorithm is vendored with only its export converted to CommonJS, because SDK 57 Router's `query-string` dependency requires that format. The MIT license is preserved, and regression tests verify query decoding and malformed input. Replace the vendor adaptation when upgrading to a compatible patched Router release. The Expo/Metro build toolchain still reports unpatched `braces` (GHSA-vfj7-8cjw-p6xm) and `node-forge` (GHSA-86w9-cpqp-85rv) advisories, plus the older `uuid` dependency in Xcode project generation (GHSA-w5hq-g745-h8pq). These tools are not imported by application screens; only trusted repository patterns and generated build configuration are used. No OTA update/signature verification feature is enabled. Keep Metro/build tooling private and review upstream patches before production signing; this project does not claim a clean npm audit.
