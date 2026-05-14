from django.db import models
from tenants.models import TenantAwareModel
from datetime import datetime, timedelta


class GSTScheme(models.Model):
    """Model to store GST scheme configuration for a pharmacy"""
    SCHEME_CHOICES = [
        ('regular', 'Regular Scheme'),
        ('composition', 'Composition Scheme'),
    ]
    
    name = models.CharField(max_length=50, choices=SCHEME_CHOICES)
    description = models.CharField(max_length=500)
    
    def __str__(self):
        return self.get_name_display()


class GSTConfiguration(TenantAwareModel):
    """Model to store GST configuration for each pharmacy"""
    SCHEME_CHOICES = [
        ('regular', 'Regular Scheme'),
        ('composition', 'Composition Scheme'),
    ]
    
    scheme = models.CharField(max_length=50, choices=SCHEME_CHOICES, default='regular')
    gst_number = models.CharField(max_length=15, unique=True)  # GST Identification Number
    legal_name = models.CharField(max_length=200)
    trade_name = models.CharField(max_length=200, null=True, blank=True)
    
    # Filing Frequency
    filing_frequency = models.CharField(
        max_length=20,
        choices=[
            ('monthly', 'Monthly'),
            ('quarterly', 'Quarterly'),
        ],
        default='monthly'
    )
    
    # Financial Year Start (e.g., April 1)
    financial_year_start_month = models.IntegerField(default=4)  # April
    financial_year_start_day = models.IntegerField(default=1)
    
    # Thresholds
    composition_turnover_limit = models.DecimalField(max_digits=12, decimal_places=2, default=40000000)  # 40 Lakhs
    regular_turnover_threshold = models.DecimalField(max_digits=12, decimal_places=2, default=4000000)   # 40 Lakhs
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        unique_together = ('tenant', 'gst_number')
    
    def __str__(self):
        return f"{self.legal_name} - {self.gst_number}"


class GSTFiling(TenantAwareModel):
    """Model to track GST filings (GSTR-1, GSTR-3B, GSTR-9, CMP-08, GSTR-4)"""
    FORM_TYPES = [
        # Regular Scheme
        ('gstr-1', 'GSTR-1 - Outward Supplies'),
        ('gstr-3b', 'GSTR-3B - Monthly Return'),
        ('gstr-9', 'GSTR-9 - Annual Return'),
        
        # Composition Scheme
        ('cmp-08', 'CMP-08 - Quarterly Return'),
        ('gstr-4', 'GSTR-4 - Annual Return (Composition)'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('prepared', 'Prepared'),
        ('filed', 'Filed'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
        ('amended', 'Amended'),
    ]
    
    # Basic Information
    gst_config = models.ForeignKey(GSTConfiguration, on_delete=models.CASCADE, related_name='filings')
    form_type = models.CharField(max_length=10, choices=FORM_TYPES)
    
    # Filing Period
    period_start = models.DateField()
    period_end = models.DateField()
    due_date = models.DateField()
    
    # Financial Details
    total_taxable_supply = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_gst_payable = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    total_gst_input_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_gst_payable = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Filing Details
    filed_on = models.DateTimeField(null=True, blank=True)
    acknowledgement_number = models.CharField(max_length=50, null=True, blank=True)
    reference_number = models.CharField(max_length=50, null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)
    
    # Penalty/Interest if any
    penalty_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    interest_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ('gst_config', 'form_type', 'period_start', 'period_end')
        ordering = ['-period_start']
    
    def __str__(self):
        return f"{self.gst_config.legal_name} - {self.get_form_type_display()} ({self.period_start})"
    
    def is_overdue(self):
        """Check if filing is overdue"""
        from django.utils import timezone
        if self.status not in ['filed', 'accepted']:
            return timezone.now().date() > self.due_date
        return False
    
    def days_until_due(self):
        """Get number of days until filing is due"""
        from django.utils import timezone
        if self.status not in ['filed', 'accepted']:
            delta = self.due_date - timezone.now().date()
            return delta.days if delta.days > 0 else 0
        return 0


class GSTReturn(TenantAwareModel):
    """Detailed information for each GST return"""
    RETURN_TYPES = [
        ('regular', 'Regular'),
        ('amended', 'Amended'),
        ('supplementary', 'Supplementary'),
    ]
    
    gst_filing = models.OneToOneField(GSTFiling, on_delete=models.CASCADE, related_name='return_details')
    return_type = models.CharField(max_length=20, choices=RETURN_TYPES, default='regular')
    
    # Supply Details
    intrastate_supply = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    interstate_supply = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    exempt_supply = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    zero_rated_supply = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Tax Details
    cgst_5pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sgst_5pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    igst_5pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    cgst_12pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sgst_12pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    igst_12pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    cgst_18pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sgst_18pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    igst_18pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    cgst_28pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sgst_28pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    igst_28pct = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Input Tax Credit Details
    cgst_input_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sgst_input_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    igst_input_credit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Reverse Charge
    reverse_charge_applicable = models.BooleanField(default=False)
    reverse_charge_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Return for {self.gst_filing}"


class GSTCompositionReturn(TenantAwareModel):
    """Simplified return for Composition Scheme filers (CMP-08, GSTR-4)"""
    gst_filing = models.OneToOneField(GSTFiling, on_delete=models.CASCADE, related_name='composition_return')
    
    # Composition Scheme Details
    total_turnover = models.DecimalField(max_digits=15, decimal_places=2)
    composition_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=1)  # Usually 1% or 2%
    composition_tax_liability = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Supplies
    supplies_within_state = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    supplies_outside_state = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Quarterly Return (CMP-08)
    quarter = models.IntegerField(choices=[(1, 'Q1'), (2, 'Q2'), (3, 'Q3'), (4, 'Q4')], null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Composition Return for {self.gst_filing}"


class GSTReminder(TenantAwareModel):
    """Reminders for GST filing deadlines"""
    REMINDER_TYPES = [
        ('due_date', 'Due Date Reminder'),
        ('overdue', 'Overdue Reminder'),
        ('filing_required', 'Filing Required'),
    ]
    
    gst_filing = models.ForeignKey(GSTFiling, on_delete=models.CASCADE, related_name='reminders')
    reminder_type = models.CharField(max_length=20, choices=REMINDER_TYPES)
    reminder_date = models.DateField()
    is_notified = models.BooleanField(default=False)
    notified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['reminder_date']
    
    def __str__(self):
        return f"{self.reminder_type} - {self.gst_filing} ({self.reminder_date})"
