from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.http import Http404
from tenancy.models import Membership


LOGIN_ROLES = {"reception": ["owner", "reception"], "doctor": ["doctor"], "patient": ["patient"]}
LOGIN_TITLES = {"reception": "Reception & secretary sign in", "doctor": "Doctor sign in", "patient": "Patient sign in"}


class WorkspaceAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        workspace = self.request.resolver_match.kwargs["workspace"]
        if user.is_superuser and workspace == "reception":
            return
        if user.is_superuser or not Membership.objects.filter(user=user, active=True,
            practice__active=True, role__in=LOGIN_ROLES[workspace]).exists():
            raise ValidationError("This account does not have active access to this sign-in area. Choose the correct sign-in page.", code="invalid_workspace")


class WorkspaceLoginView(LoginView):
    template_name = "portal/login.html"
    authentication_form = WorkspaceAuthenticationForm
    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if kwargs["workspace"] not in LOGIN_ROLES:
            raise Http404()
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        workspace = self.kwargs["workspace"]
        membership = Membership.objects.filter(user=form.get_user(), active=True, practice__active=True,
            role__in=LOGIN_ROLES[workspace]).order_by("practice__name").first()
        self.request.session.pop("portal_practice", None)
        if membership:
            self.request.session["portal_practice"] = str(membership.practice_id)
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        return super().get_context_data(**kwargs, title=LOGIN_TITLES[self.kwargs["workspace"]], login_workspace=self.kwargs["workspace"])
