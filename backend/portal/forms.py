from django import forms
from django.contrib.auth import get_user_model
from clinical.models import Encounter
from patients.models import Patient
from scheduling.models import Appointment, Service
from tenancy.models import Membership


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ["file_number", "given_name", "family_name", "date_of_birth", "mobile", "email", "portal_user"]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, practice, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["portal_user"].queryset = get_user_model().objects.filter(is_active=True,
            membership__practice=practice, membership__active=True, membership__role="patient").distinct()
        self.fields["portal_user"].label = "Patient app account (optional)"
        self.fields["portal_user"].help_text = "Choose this patient's own account to enable personal notifications."



class ServiceForm(forms.ModelForm):
    class Meta:
        model = Service
        fields = ["name", "duration_minutes", "price_cents", "deposit_cents"]

    def clean_duration_minutes(self):
        value = self.cleaned_data["duration_minutes"]
        if value < 1:
            raise forms.ValidationError("Duration must be at least one minute.")
        return value


class BookingForm(forms.Form):
    patient = forms.ModelChoiceField(queryset=Patient.objects.none())
    practitioner = forms.ModelChoiceField(queryset=get_user_model().objects.none())
    service = forms.ModelChoiceField(queryset=Service.objects.none())
    starts_at = forms.DateTimeField(label="Appointment time (South Africa / SAST)", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    reason_for_visit = forms.CharField(label="Reported symptoms / reason for visit", required=False, max_length=2000, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, practice, user, role, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.filter(practice=practice, active=True).order_by("family_name")
        if role == "patient":
            self.fields["patient"].queryset = self.fields["patient"].queryset.filter(portal_user=user)
            self.fields["reason_for_visit"].required = True
        users = get_user_model().objects.filter(membership__practice=practice, membership__active=True,
            membership__role__in=[Membership.Role.DOCTOR, Membership.Role.NURSE], is_active=True)
        if role in [Membership.Role.DOCTOR, Membership.Role.NURSE]:
            users = users.filter(pk=user.pk)
        self.fields["practitioner"].queryset = users.distinct()
        self.fields["service"].queryset = Service.objects.filter(practice=practice)
        self.fields["patient"].label_from_instance = lambda p: f"{p.given_name} {p.family_name} · {p.file_number}"
        self.fields["service"].label_from_instance = lambda s: f"{s.name} · {s.duration_minutes} min"


class PrescriptionForm(forms.Form):
    encounter = forms.ModelChoiceField(queryset=Encounter.objects.none())
    medication_name = forms.CharField(max_length=180)
    dosage = forms.CharField(max_length=100)
    frequency = forms.CharField(max_length=100)
    duration = forms.CharField(max_length=100, required=False)
    instructions = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))

    def __init__(self, *args, practice, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["encounter"].queryset = Encounter.objects.filter(practice=practice, practitioner=user).select_related("patient")
        self.fields["encounter"].label_from_instance = lambda e: f"{e.patient.given_name} {e.patient.family_name} · {e.started_at:%d %b %Y}"


class IntakeForm(forms.ModelForm):
    reason_for_visit = forms.CharField(label="Reported symptoms / reason for visit", max_length=2000, required=False, widget=forms.Textarea(attrs={"rows":3}))
    blood_pressure_systolic = forms.IntegerField(label="Blood pressure: systolic (mmHg)", min_value=1, max_value=350, required=False)
    blood_pressure_diastolic = forms.IntegerField(label="Blood pressure: diastolic (mmHg)", min_value=1, max_value=250, required=False)

    class Meta:
        model = Appointment
        fields = ["reason_for_visit", "blood_pressure_systolic", "blood_pressure_diastolic"]
        labels = {"reason_for_visit": "Reported symptoms / reason for visit"}
        widgets = {"reason_for_visit": forms.Textarea(attrs={"rows": 3})}

    def clean(self):
        values = super().clean()
        systolic, diastolic = values.get("blood_pressure_systolic"), values.get("blood_pressure_diastolic")
        if (systolic is None) != (diastolic is None):
            raise forms.ValidationError("Enter both blood pressure readings, or leave both blank if not yet measured.")
        return values


class PatientAccountForm(PatientForm):
    class Meta(PatientForm.Meta):
        fields = ["portal_user"]


class PracticeUserForm(forms.ModelForm):
    delivery = forms.ChoiceField(label="Account setup", choices=[
        ("invite", "Email a secure invitation"), ("password", "Set an initial password privately")])
    password1 = forms.CharField(label="Initial password", required=False, widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirm password", required=False, widget=forms.PasswordInput)
    patient = forms.ModelChoiceField(queryset=Patient.objects.none(), required=False,
        label="Patient record", help_text="Add the patient record first, then select it here.")

    class Meta:
        model = get_user_model()
        fields = ["username", "first_name", "last_name", "email"]

    def __init__(self, *args, practice, account_role, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["last_name"].required = True
        if account_role == "patient":
            self.fields["patient"].required = True
            self.fields["patient"].queryset = Patient.objects.filter(
                practice=practice, active=True, portal_user__isnull=True).order_by("family_name", "given_name")
            self.fields["patient"].label_from_instance = lambda p: f"{p.given_name} {p.family_name} · {p.file_number}"
        else:
            del self.fields["patient"]

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email and get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Use an email address belonging only to this account owner.")
        return email

    def clean(self):
        values = super().clean()
        if values.get("delivery") == "invite":
            from securityguard.accounts import mail_ready
            if not values.get("email"):
                self.add_error("email", "An email address is required for an invitation.")
            if not mail_ready():
                self.add_error("delivery", "Email invitations are unavailable until your HTTPS address and email service are configured.")
        elif values.get("delivery") == "password":
            from django.contrib.auth.password_validation import validate_password
            password = values.get("password1", "")
            if password != values.get("password2", ""):
                self.add_error("password2", "Passwords do not match.")
            try:
                candidate = get_user_model()(username=values.get("username", ""),
                    first_name=values.get("first_name", ""), last_name=values.get("last_name", ""), email=values.get("email", ""))
                validate_password(password, candidate)
            except forms.ValidationError as error:
                self.add_error("password1", error)
        return values

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data["delivery"] == "invite":
            user.set_unusable_password()
        else:
            user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user
