from django.db import models
from tenants.models import TenantAwareModel


class DoctorModel(TenantAwareModel):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    specialization = models.CharField(max_length=200, null=True, blank=True)
    is_default = models.BooleanField(default=False)  # To mark a default doctor for prescriptions
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name