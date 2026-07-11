from django.db import models
from django.conf import settings
from tenants.models import TenantAwareModel

class PrescriptionScanLog(TenantAwareModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Scan by {self.user} at {self.created_at} (Tenant: {self.tenant.name if self.tenant else 'None'})"

    class Meta:
        verbose_name_plural = "Prescription Scan Logs"
