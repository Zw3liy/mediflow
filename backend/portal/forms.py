from django import forms
from django.contrib.auth import get_user_model
from clinical.models import Encounter
from patients.models import Patient
from scheduling.models import Service
from tenancy.models import Membership


class PatientForm(forms.ModelForm):
    class Meta:
        model = Patient
        fields = ["file_number", "given_name", "family_name", "date_of_birth", "mobile", "email"]
        widgets = {"date_of_birth": forms.DateInput(attrs={"type": "date"})}


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
    starts_at = forms.DateTimeField(label="Appointment time (UTC)", widget=forms.DateTimeInput(attrs={"type": "datetime-local"}))

    def __init__(self, *args, practice, user, role, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["patient"].queryset = Patient.objects.filter(practice=practice, active=True).order_by("family_name")
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
