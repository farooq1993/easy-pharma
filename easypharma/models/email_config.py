from django.db import models
from tenants.models import TenantAwareModel

class EmailConfig(TenantAwareModel):
    email_address = models.EmailField(help_text="User's Gmail address")
    app_password = models.CharField(max_length=255, help_text="Gmail 16-character App Password")
    is_active = models.BooleanField(default=True, help_text="Enable or disable email invoice fetching")
    last_sync = models.DateTimeField(null=True, blank=True, help_text="Timestamp of last email synchronization")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Gmail Config for {self.email_address} (Tenant: {self.tenant.name if self.tenant else 'None'})"
