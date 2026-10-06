# MediFlow role workspaces

Open `/app/` and sign in with an existing Django user account. An active practice
membership selects the Admin (Owner), Doctor, Reception, or Patient workspace.
Superusers can select any active practice; appointment approval still requires
an active Owner or Reception membership in that practice.

- Admin: view practice activity and team, add patients and consultation services.
- Reception: add patients, request appointments, approve or reject requests.
- Doctor: request appointments, open approved consultations, create prescription
  drafts, and confirm review before issuing prescriptions.
- Patient: view their own appointments and issued prescriptions; download only
  their own clean, released documents.

Link a patient record's `portal_user` to its login account and give that account
an active Patient membership to enable its patient workspace. Clinic records are
scoped to the selected practice. All appointment input and display times use UTC.
The responsive portal uses the same server on desktop and mobile browsers.
Rebuild the Compose web image to install portal code and styles.
