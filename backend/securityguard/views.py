import base64
import secrets
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import SetPasswordForm
from django.db import transaction
from django.db.models import F
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.cache import never_cache
from django_otp import login as otp_login, verify_token
from django_otp.plugins.otp_totp.models import TOTPDevice
from auditlog.services import record_audit_event
from tenancy.models import Membership
from .accounts import digest_token
from .forms import CodeForm, MFACodeForm
from .models import AccountInvitation, RecoveryCode


def recovery_digest(code):
    return salted_hmac('mediflow.recovery', code.strip().upper(), algorithm='sha256').hexdigest()


@never_cache
@login_required
def mfa(request):
    device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    if device is None:
        return redirect('/app/security/mfa/setup/')
    form = CodeForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        code = form.cleaned_data['code'].strip()
        valid = verify_token(request.user, device.persistent_id, code)
        if not valid:
            with transaction.atomic():
                recovery = RecoveryCode.objects.select_for_update().filter(
                    user=request.user, digest=recovery_digest(code)).first()
                if recovery:
                    recovery.delete()
                    valid = device
        if valid:
            otp_login(request, device)
            request.session.cycle_key()
            return redirect('/app/')
        form.add_error('code', 'Invalid or already used code. Wait before trying again.')
    return render(request, 'portal/security_form.html', {'title': 'Verify your identity', 'form': form})


@never_cache
@login_required
def mfa_setup(request):
    if TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
        return redirect('/app/security/mfa/')
    form = MFACodeForm(request.POST if request.method == 'POST' else None)
    # Never put the shared secret in a browser cookie or URL.
    with transaction.atomic():
        from django.contrib.auth import get_user_model
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        device, _ = TOTPDevice.objects.get_or_create(user=request.user, name='Primary', confirmed=False)
    if request.method == 'POST' and form.is_valid():
        if not request.user.check_password(form.cleaned_data['password']):
            form.add_error('password', 'Current password is incorrect.')
        elif verify_token(request.user, device.persistent_id, form.cleaned_data['code']):
            with transaction.atomic():
                device = TOTPDevice.objects.select_for_update().get(pk=device.pk)
                device.confirmed = True
                device.save(update_fields=['confirmed'])
                codes = [secrets.token_hex(8).upper() for _ in range(10)]
                RecoveryCode.objects.filter(user=request.user).delete()
                RecoveryCode.objects.bulk_create([
                    RecoveryCode(user=request.user, digest=recovery_digest(c)) for c in codes])
            otp_login(request, device)
            request.session.cycle_key()
            return render(request, 'portal/recovery_codes.html', {'codes': codes, 'title': 'Save your recovery codes'})
        else:
            form.add_error('code', 'Invalid code. Wait before trying again.')
    secret = base64.b32encode(bytes.fromhex(device.key)).decode().rstrip('=')
    return render(request, 'portal/security_form.html', {'title': 'Set up an authenticator',
        'form': form, 'setup_secret': secret})


@never_cache
def accept_invitation(request, token):
    now = timezone.now()
    invitation = AccountInvitation.objects.filter(token_digest=digest_token(token),
        accepted_at__isnull=True, expires_at__gt=now, user__is_active=True,
        practice__active=True, user__membership__practice_id=F('practice_id'),
        user__membership__active=True).select_related('user', 'practice').first()
    if not invitation:
        return render(request, 'portal/security_form.html', {'title': 'Invitation unavailable',
            'detail': 'This link has expired, was used, or access was disabled. Ask your practice for a new invitation.'}, status=400)
    form = SetPasswordForm(invitation.user, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            from tenancy.models import Practice
            Practice.objects.select_for_update().get(pk=invitation.practice_id)
            invitation = AccountInvitation.objects.select_for_update().get(pk=invitation.pk)
            if (invitation.accepted_at or invitation.expires_at <= timezone.now()
                    or not Membership.objects.filter(user=invitation.user, practice=invitation.practice, active=True).exists()):
                return render(request, 'portal/security_form.html', {'title': 'Invitation unavailable'}, status=400)
            from django.contrib.auth import get_user_model
            locked_user = get_user_model().objects.select_for_update().get(pk=invitation.user_id)
            if not locked_user.is_active:
                return render(request, 'portal/security_form.html', {'title': 'Invitation unavailable'}, status=400)
            form.user = locked_user
            form.save()
            invitation.accepted_at = timezone.now()
            invitation.save(update_fields=['accepted_at'])
            record_audit_event(practice=invitation.practice, actor=invitation.user,
                action='account.invitation_accepted', object_type='user', object_id=invitation.user_id,
                purpose='Activate invited account', outcome='success')
        messages.success(request, 'Password set. Sign in to your own workspace.')
        return redirect('/app/login/')
    response = render(request, 'portal/security_form.html', {'title': 'Set your account password', 'form': form})
    return response
