from django.db import models
from tenants.models import TenantAwareModel
from django.conf import settings


class FinancialYear(TenantAwareModel):
    fy_code = models.CharField(max_length=20, help_text="e.g. 25-26 or 2025-26")
    start_date = models.DateField(help_text="Start date of FY (e.g. 01-Apr-2025)")
    end_date = models.DateField(help_text="End date of FY (e.g. 31-Mar-2026)")
    is_active = models.BooleanField(default=True)
    is_locked = models.BooleanField(default=False, help_text="Freeze Books toggle: when True, entries for this FY are locked.")
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='locked_financial_years')
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-start_date']
        unique_together = ('tenant', 'fy_code')
        verbose_name = "Financial Year"
        verbose_name_plural = "Financial Years"

    def __str__(self):
        status = "Locked 🔒" if self.is_locked else "Active 🟢"
        return f"FY {self.fy_code} ({self.start_date} to {self.end_date}) [{status}]"
