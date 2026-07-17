from django.db import models
from tenants.models import Tenant,SharedModel, TenantAwareModel


class GeneralSetup(TenantAwareModel):
    EXPIRY_DATE_FORMAT_CHOICES = [
        ('text', 'Text Input (MM/YY)'),
        ('dropdown', 'Months/Years Dropdown'),
    ]

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='general_setup')

    # Sale Setup options
    default_payment_mode = models.CharField(max_length=20, default='cash', choices=[
        ('cash', 'Cash'),
        ('card', 'Card'),
        ('upi', 'UPI / QR Code'),
        ('credit', 'Credit')
    ])
    require_customer_phone = models.BooleanField(default=False, help_text="Require customer phone number on sales invoice")
    print_invoice_after_save = models.BooleanField(default=True, help_text="Automatically open print dialog after saving sale")

    # Purchase Setup options
    expiry_date_format = models.CharField(
        max_length=20, 
        choices=EXPIRY_DATE_FORMAT_CHOICES, 
        default='text',
        help_text="Choose how expiry date is entered during purchase entry"
    )
    default_tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18.0, help_text="Default tax rate for new products")
    auto_update_selling_price = models.BooleanField(default=False, help_text="Automatically adjust product selling price when purchase cost changes")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"GeneralSetup for {self.tenant.pharmacy_name}"
