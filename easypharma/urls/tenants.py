from django.urls import path
from easypharma.views.tenants import RegisterTenantView

urlpatterns = [
    path("register-pharmacy/", RegisterTenantView.as_view(), name="register_pharmacy"),
]
