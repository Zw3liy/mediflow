from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from .models import Membership, Practice


class TenantAdminAccessTests(TestCase):
    def test_superuser_can_access_practice_and_membership_administration(self):
        user = get_user_model().objects.create_superuser(username="platform-admin", password="test-password")
        self.client.force_login(user)
        for model in (Practice, Membership):
            self.assertIn(model, admin.site._registry)
            response = self.client.get(reverse(f"admin:tenancy_{model._meta.model_name}_changelist"))
            self.assertEqual(response.status_code, 200)

    def test_staff_with_model_permissions_cannot_access_global_tenant_admin(self):
        user = get_user_model().objects.create_user(username="tenant-staff", is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="tenancy"))
        self.client.force_login(user)
        for model in (Practice, Membership):
            for action in ("changelist", "add"):
                response = self.client.get(reverse(f"admin:tenancy_{model._meta.model_name}_{action}"))
                self.assertEqual(response.status_code, 403)
            model_admin = admin.site._registry[model]
            request = response.wsgi_request
            self.assertFalse(model_admin.has_module_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
