from types import SimpleNamespace
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from rest_framework.authentication import SessionAuthentication
from mobile_api.registrations import Registrations,PatientRegistration,AccountRegistration
from .views import scope,ROLE_PATHS
class BrowserAdmin:
    authentication_classes=[SessionAuthentication]
    def initial(self,request,*args,**kwargs):
        super().initial(request,*args,**kwargs)
        practice,role,_=scope(request,["owner","reception"])
        request.auth=SimpleNamespace(practice=practice,current_role=role)
class BrowserRegistrations(BrowserAdmin,Registrations):pass
class BrowserPatient(BrowserAdmin,PatientRegistration):pass
class BrowserAccount(BrowserAdmin,AccountRegistration):pass
@never_cache
@login_required
def page(request):
    practice,role,practices=scope(request,["owner","reception"])
    return render(request,"portal/registrations.html",{"practice":practice,"role":role,"practices":practices,"workspace":ROLE_PATHS.get(role),"title":"Manage registrations"})
