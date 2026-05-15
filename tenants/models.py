from django.db import models
from django.conf import settings

class Tenant(models.Model):
    name = models.CharField(max_length=100)
    subdomain = models.CharField(max_length=50, unique=True)
    database_name = models.CharField(max_length=100, blank=True)
    schema_name = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='owned_tenants')
    
    # Pharmacy details
    pharmacy_name = models.CharField(max_length=200)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    license_number = models.CharField(max_length=100)
    gst_number = models.CharField(max_length=50, null=True, blank=True)
    invoice_message = models.TextField(null=True, blank=True)
    access_key = models.CharField(max_length=100, blank=True, unique=True, null=True)
    
    def __str__(self):
        return f"{self.pharmacy_name} ({self.subdomain})"
    
    def save(self, *args, **kwargs):
        if not self.database_name:
            self.database_name = f"tenant_{self.subdomain}"
        if not self.schema_name:
            self.schema_name = f"schema_{self.subdomain}"
        if not self.access_key:
            import uuid
            self.access_key = str(uuid.uuid4()).upper()[:12] # Generate a 12-char key
        super().save(*args, **kwargs)

class TenantAwareModel(models.Model):
    """
    Base model for all tenant-specific data.
    Inherit from this for models that should be isolated per tenant.
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True)
    
    class Meta:
        abstract = True

class SharedModel(models.Model):
    """
    Base model for shared data across all tenants.
    Inherit from this for models that should be shared.
    """
    class Meta:
        abstract = True