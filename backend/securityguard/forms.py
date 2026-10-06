from django import forms
from django.contrib.auth.forms import PasswordResetForm
from django.conf import settings
from .accounts import mail_ready
from .models import EmailTask


class CodeForm(forms.Form):
    code = forms.CharField(label='Authenticator or recovery code', max_length=64,
        widget=forms.TextInput(attrs={'autocomplete': 'one-time-code'}))


class MFACodeForm(CodeForm):
    code = forms.RegexField(
        regex=r'^[0-9]{6}$', label='Six-digit code from your authenticator app',
        max_length=6, min_length=6,
        help_text='Open the MediFlow entry in your authenticator app and enter its current six-digit number. Do not enter your username or the setup key.',
        widget=forms.TextInput(attrs={'autocomplete': 'one-time-code', 'inputmode': 'numeric', 'pattern': '[0-9]{6}', 'placeholder': '123456'}))
    password = forms.CharField(label='Current MediFlow password',
        widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))


class QueuedPasswordResetForm(PasswordResetForm):
    def save(self, **kwargs):
        if not mail_ready():
            return
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        for user in self.get_users(self.cleaned_data['email']):
            # A shared email address cannot recover another person's account.
            from django.contrib.auth import get_user_model
            if get_user_model().objects.filter(email__iexact=user.email, is_active=True).count() != 1:
                continue
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            url = settings.PUBLIC_BASE_URL + f'/app/password/reset/{uid}/{token}/'
            EmailTask.objects.create(recipient=user.email, subject='MediFlow password reset',
                body=f'Reset your password within one hour:\n{url}\n'
                     'If you did not request this, ignore this email.\n')
