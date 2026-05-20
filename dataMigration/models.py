from django.db import models
from tenants.models import TenantAwareModel
from django.conf import settings

class MigrationLog(TenantAwareModel):
    IMPORT_TYPES = [
        ('company', 'Company Master'),
        ('supplier', 'Supplier Master'),
        ('product', 'Product Master'),
        ('stock', 'Stock & Batches'),
    ]
    
    import_type = models.CharField(max_length=20, choices=IMPORT_TYPES)
    source_name = models.CharField(max_length=100, default="Text Copy-Paste")
    records_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True
    )
    status = models.CharField(
        max_length=20, 
        default='SUCCESS', 
        choices=[
            ('PENDING', 'Pending'),
            ('PROCESSING', 'Processing'),
            ('SUCCESS', 'Success'),
            ('ROLLED_BACK', 'Rolled Back'),
            ('FAILED', 'Failed')
        ]
    )
    progress_percent = models.IntegerField(default=0)
    error_message = models.TextField(blank=True, null=True)
    
    # Store primary keys of created records to allow full rollback cleanup
    # e.g., {"created_ids": [101, 102], "auto_created_dependencies": {"DrugCompany": [12]}}
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.get_import_type_display()} - {self.records_count} rows ({self.created_at.strftime('%Y-%m-%d %H:%M')})"
