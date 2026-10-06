from django.contrib import admin

from .models import Membership, Practice


class SuperuserOnlyAdmin(admin.ModelAdmin):
    """Tenant administration is global and restricted to platform superusers."""

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        return self.has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.has_module_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_module_permission(request)


@admin.register(Practice)
class PracticeAdmin(SuperuserOnlyAdmin):
    list_display = ("name", "active", "id")
    list_filter = ("active",)
    search_fields = ("name",)


@admin.register(Membership)
class MembershipAdmin(SuperuserOnlyAdmin):
    list_display = ("user", "practice", "role", "active")
    list_filter = ("role", "active", "practice")
    search_fields = ("user__username", "practice__name")
    autocomplete_fields = ("user", "practice")
    list_select_related = ("user", "practice")
