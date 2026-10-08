from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as ModelValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError, PermissionDenied
from portal.forms import PatientForm, PracticeUserForm
from patients.models import Patient
from tenancy.models import Membership, Practice
from securityguard.models import AccountInvitation
from auditlog.services import record_audit_event
from .views import MobileBase

DETAILS = ["file_number", "given_name", "family_name", "date_of_birth", "mobile", "email", "address", "emergency_contact_name", "emergency_contact_mobile"]
def audit(request, action, obj):
    record_audit_event(practice=request.auth.practice,actor=request.user,action=action,object_type=obj.__class__.__name__,object_id=str(obj.pk),purpose="Manage practice registrations",outcome="success")
def patient_data(p):
    return {"id":str(p.pk),"active":p.active,"portal_user":p.portal_user_id,**{k:str(getattr(p,k) or '') for k in DETAILS}}
class Registrations(MobileBase):
    def get(self, request):
        self.roles(request,["owner","reception"])
        return Response({"patients":[patient_data(p) for p in Patient.objects.filter(practice=request.auth.practice).order_by("family_name")],"accounts":[{"id":m.pk,"username":m.user.username,"first_name":m.user.first_name,"last_name":m.user.last_name,"email":m.user.email,"role":m.role,"active":m.active} for m in Membership.objects.filter(practice=request.auth.practice,role__in=["doctor","patient"],user__is_superuser=False,user__is_staff=False).select_related("user")]})
    @transaction.atomic
    def post(self, request):
        self.roles(request,["owner","reception"])
        role=request.data.get("role")
        if role not in ["doctor","patient"]: raise ValidationError("Choose doctor or patient.")
        Practice.objects.select_for_update().get(pk=request.auth.practice.pk)
        form=PracticeUserForm(request.data,practice=request.auth.practice,account_role=role)
        if not form.is_valid(): raise ValidationError(form.errors.get_json_data())
        try:
            with transaction.atomic():
                user=form.save(); Membership.objects.create(practice=request.auth.practice,user=user,role=role)
                if role=="patient":
                    patient=get_object_or_404(Patient.objects.select_for_update(),pk=form.cleaned_data["patient"].pk,practice=request.auth.practice,active=True,portal_user__isnull=True)
                    patient.portal_user=user;patient.save(update_fields=["portal_user","updated_at"])
                if form.cleaned_data["delivery"]=="invite":
                    from securityguard.accounts import queue_invitation
                    queue_invitation(user,request.auth.practice)
                audit(request,"account.created",user)
        except IntegrityError: raise ValidationError("Account details are already in use.")
        return Response({"id":user.pk},status=201)
class PatientRegistration(MobileBase):
    @transaction.atomic
    def patch(self, request, pk):
        self.roles(request,["owner","reception"])
        p=get_object_or_404(Patient.objects.select_for_update(),pk=pk,practice=request.auth.practice)
        if "active" in request.data:
            if not isinstance(request.data["active"],bool): raise ValidationError("Active must be true or false.")
            p.active=request.data["active"]
            if p.portal_user_id:
                Membership.objects.filter(practice=request.auth.practice,user_id=p.portal_user_id,role="patient").update(active=p.active)
                if not p.active: AccountInvitation.objects.filter(practice=request.auth.practice,user_id=p.portal_user_id,accepted_at__isnull=True).update(expires_at=timezone.now())
        else:
            data={k:getattr(p,k) or '' for k in DETAILS};data.update({k:v for k,v in request.data.items() if k in DETAILS});data["portal_user"]=p.portal_user_id or ''
            form=PatientForm(data,instance=p,practice=request.auth.practice)
            # Preserve an existing disabled login while editing demographics.
            if p.portal_user_id: form.fields["portal_user"].queryset=get_user_model().objects.filter(pk=p.portal_user_id)
            if not form.is_valid():raise ValidationError(form.errors.get_json_data())
            p=form.save(commit=False)
        try:
            p.full_clean();p.save()
        except ModelValidationError as error: raise ValidationError(error.message_dict)
        audit(request,"patient.registration.updated",p)
        return Response(patient_data(p))
class AccountRegistration(MobileBase):
    @transaction.atomic
    def patch(self, request, pk):
        self.roles(request,["owner","reception"])
        m=get_object_or_404(Membership.objects.select_for_update(),pk=pk,practice=request.auth.practice,role__in=["doctor","patient"],user__is_superuser=False,user__is_staff=False)
        if m.user_id==request.user.pk: raise PermissionDenied("You cannot edit your own access here.")
        if "active" in request.data:
            if not isinstance(request.data["active"],bool):raise ValidationError("Active must be true or false.")
            m.active=request.data["active"];m.save(update_fields=["active"])
            if not m.active:AccountInvitation.objects.filter(practice=request.auth.practice,user_id=m.user_id,accepted_at__isnull=True).update(expires_at=timezone.now())
        else:
            if Membership.objects.filter(user_id=m.user_id).exclude(practice=request.auth.practice).exists():raise ValidationError("This shared account must be edited by the system administrator.")
            from django import forms
            class EditForm(forms.ModelForm):
                class Meta:
                    model=get_user_model();fields=["username","first_name","last_name","email"]
                def clean_email(self):
                    email=self.cleaned_data["email"]
                    if email and get_user_model().objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():raise forms.ValidationError("Email already in use.")
                    return email
            user=get_user_model().objects.select_for_update().get(pk=m.user_id)
            data={k:getattr(user,k) for k in EditForm.Meta.fields};data.update({k:v for k,v in request.data.items() if k in data})
            form=EditForm(data,instance=user)
            if not form.is_valid():raise ValidationError(form.errors.get_json_data())
            form.save()
        audit(request,"account.registration.updated",m)
        return Response({"saved":True})
