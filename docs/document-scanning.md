# Patient document scanning

In the installed MediFlow app, reception and owner accounts open **Scan patient document**. Take a picture or choose a document photograph, then tap **Read document**. Review the original picture, recognised text and proposed demographic fields. Select an existing patient or create a new record, correct the fields, approve the review checkbox, and save. Existing-patient changes are shown before confirmation. The server rejects updates based on an outdated patient record; refresh the directory and review again.

The original JPEG/PNG, a searchable PDF with the machine-recognised text layer, and separately corrected text are stored privately in the patient's file. Saved documents and unfinished drafts can be reopened from the scanning screen. A PDF can be opened through the phone's share sheet. Documents are not automatically released to patient accounts. Access requires an authenticated reception/owner session scoped to the practice, and downloads are audited.

This first release handles one photographed page at a time, with English printed text. It does not interpret diagnoses or prescriptions. Suggestions use labelled first/given name, surname/family name, patient/file number, date of birth, phone, email and address fields. Ambiguous numerical dates and conflicting repeated labels are left for manual entry. Handwriting, blur, unlabelled forms and unusual layouts may need manual correction. A scan with no recognised text can still be reviewed and saved manually, or discarded and retaken.

## Deployment

Deploy the backend branch after review and checks, rebuilding the web and maintenance images. The web startup applies the patient-address and document-scan migrations. Tesseract with its English data and Pillow are included in the backend image. The existing ClamAV service must be healthy; recognition fails closed if malware checking is unavailable. No cloud OCR credentials are needed and OCR runs on the practice server.

The maintenance service must mount the same private_documents volume as web. It removes abandoned, unreviewed drafts older than 24 hours during its daily maintenance loop. Reviewed patient files are not removed. An operator can run `python manage.py cleanup_document_scans` manually.

A new native build is required for camera/photo permissions and the image-picker/sharing modules. Updating the backend alone will not change an already installed APK. In the mobile checkout, install locked dependencies with `npm ci`, then use `npx eas-cli@latest build --platform android --profile preview` with the existing Expo project and Firebase configuration. iOS uses its existing signing/build workflow.

Test with fictional records: capture a clear intake form, verify OCR, create a patient, scan another page into that same patient, verify the displayed change review, reopen the image and PDF, and confirm camera permission and PDF opening on the installed phone. Do not claim phone verification from bundle export alone.

## Limits and verification

Images are limited to 8 MB and 20 megapixels, restricted to single JPEG/PNG images, malware checked before decoding, and normalised for OCR while preserving the original upload. OCR has a 20-second processing timeout and uploads are throttled to three per minute per authenticated user. Draft storage is cleaned up on failed writes; database review is transactional and repeated save requests cannot update demographics twice.

Automated tests cover local OCR/PDF generation, ambiguous suggestions, validation, scanner failures, practice/role isolation, explicit review, existing-patient version checking and login preservation, duplicate file numbers, private downloads, draft discard and expiry cleanup. Mobile typecheck, lint, existing tests and Android/iOS bundle exports are also required.

## Web dashboard and mobile variants

Reception/admin now have **Scan documents** in the sidebar and **Scan patient document** beside the patient directory. `/app/scans/` uses the same reviewed scan workflow as the native app, with browser-session authentication and mandatory CSRF validation for writes. Uploaded images, draft text, saved PDFs and patient updates remain practice scoped. On phones, the image upload can offer the camera; desktop staff can choose a saved photograph. The original image and PDF are served through authenticated, audited endpoints.

The web **Manage team** link now goes to MediFlow account management. Mobile clinical headings show the signed-in doctor's display name. The manual's caption/theme exercises are applied (`YOUR CARE, YOUR TIME`, teal `#126b80`). The mobile login offers an optional authenticator-code switch rather than presenting it as always required; enforcement remains the server's setting.

Optional EAS profiles `patient-preview`, `doctor-preview` and `reception-preview` provide distinct application identities with a fixed role sign-in, alongside the existing combined `preview` app. These profiles are implemented, not prebuilt installation files. New native identities need their own matching Firebase/Apple configuration and signing setup before claiming background notification support. Server permission checks remain authoritative.

The GitHub Android preview now includes arm64 phone and x86_64 emulator architectures. It is a test-signed preview, distinct from the existing EAS-signed installation. Use an EAS preview build with the existing account and credentials for an update compatible with that installed app.

## Ubuntu server update and EAS build

After the branch has been published, keep the existing tunnel running and paste into the Ubuntu server terminal:

```bash
cd ~/projects/mediflow &&
git fetch origin feature/patient-document-scanning &&
git merge --ff-only origin/feature/patient-document-scanning &&
docker compose --profile automation build web maintenance &&
docker compose run --rm --no-deps web python manage.py check_production &&
docker compose --profile automation up -d --force-recreate --wait --wait-timeout 180 web maintenance
```

Then check `http://127.0.0.1:8000/health/ready/` with the existing forwarded-HTTPS header and open `/app/scans/` through the current HTTPS tunnel. This preserves `.env`, including the chosen MFA requirement, and existing database/private-document volumes. If a fast-forward merge fails, inspect the branch difference before proceeding; do not reset or discard local work.

In the separate mobile checkout:

```bash
cd ~/projects/mediflow-mobile &&
git fetch origin feature/patient-document-scanning &&
git merge --ff-only origin/feature/patient-document-scanning &&
cd mobile &&
npm ci &&
npx eas-cli@latest build --platform android --profile preview
```

Use the existing Expo project, Firebase file environment variable and signing credentials. The signed cloud build requires that account's authenticated EAS session; it cannot be claimed from local bundle tests. Backend deployment requires execution on the user's Ubuntu server.

## Photo recognition and document fields
Recognition normalizes contrast, enlarges small photographs and sharpens text, then compares automatic-page and single-block Tesseract layouts using word confidence. Handwriting still requires review; accuracy is not guaranteed. The original upload is preserved.

Web and native review screens provide editable certificate fields and up to 50 custom label/value entries. Values are stored with the document, independently of patient demographics and clinical records. Corrected text and document entries do not modify the original image or the machine-generated searchable PDF.
