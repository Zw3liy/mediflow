# Reception, doctor and patient workflow

Open `/app/login/` and choose Reception / secretary, Doctor, or Patient. The
separate forms authenticate existing Django accounts and require the appropriate
active membership in an active practice. Superusers use Reception sign in and
retain access to practice administration. Roles are enforced on every action.

1. Patient or staff requests a future appointment. Patients can select only their
   own linked records, and describe their reported symptoms.
2. Reception records symptoms and optional measured blood pressure, then approves
   the request. The assigned doctor receives a private notification with the
   patient name, scheduled time, reported symptoms and recorded BP.
3. The assigned doctor approves the appointment. The linked patient receives a
   personal notification with their name, doctor, practice and scheduled time.
4. On the appointment day the doctor can send a Ready now alert to the next
   patient in time order. After opening and completing that consultation, the
   next patient advances in the queue. Repeated approval/call requests do not
   duplicate notifications.

Portal times use South Africa / SAST (Africa/Johannesburg); timestamps remain
stored in UTC. Doctor approval is a separate clinical-readiness timestamp and
preserves the existing payment and appointment status workflow.

Notifications refresh every 15 seconds while the app is open, and refresh when
returning to the tab. They remain in the patient's personal inbox when reopening
the app. This implements in-app notifications, not operating-system push alerts,
SMS or email delivery when the app is closed.

Create a patient login in Django administration, add its active Patient practice
membership, then use Patient directory → Link app account for the matching patient
record. Existing users and memberships are preserved. Link only the patient's own
account. Staff accounts use the Reception or Doctor membership roles.

BP must include both readings or neither. A blank reading means Not yet measured.
The app records the staff member and measurement-entry time; it does not diagnose
or interpret readings. Intake cannot be changed through this screen after doctor
approval. Rebuild the Compose web image; startup applies the included migrations.
