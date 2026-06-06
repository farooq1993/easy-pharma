from django.db import models
from tenants.models import TenantAwareModel


class CsvImportMapping(TenantAwareModel):
    OBJECT_TYPE_CHOICES = [
        ('purchase', 'Purchase'),
    ]

    name = models.CharField(max_length=150)
    object_type = models.CharField(max_length=50, choices=OBJECT_TYPE_CHOICES, default='purchase')
    mapping = models.JSONField(default=dict, blank=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('tenant', 'name', 'object_type')
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_object_type_display()})"
