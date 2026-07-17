from django.db import models
from tenants.models import TenantAwareModel
from easypharma.models.Items import Products

class DraftPurchaseInvoice(TenantAwareModel):
    supplier_name = models.CharField(max_length=200)
    supplier_gstin = models.CharField(max_length=20, null=True, blank=True)
    invoice_number = models.CharField(max_length=100)
    invoice_date = models.DateField(null=True, blank=True)
    sub_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    attachment_path = models.CharField(max_length=500, null=True, blank=True, help_text="Local path to downloaded PDF/Image")
    status = models.CharField(
        max_length=20, 
        default='Pending', 
        choices=[('Pending', 'Pending'), ('Applied', 'Applied'), ('Rejected', 'Rejected')]
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Draft Purchase INV: {self.invoice_number} from {self.supplier_name} ({self.status})"

class DraftPurchaseItem(TenantAwareModel):
    draft_invoice = models.ForeignKey(DraftPurchaseInvoice, on_delete=models.CASCADE, related_name='items')
    raw_product_name = models.CharField(max_length=255, help_text="Product name as read from PDF")
    matched_product = models.ForeignKey(Products, on_delete=models.SET_NULL, null=True, blank=True)
    batch_number = models.CharField(max_length=100, null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    free_quantity = models.PositiveIntegerField(default=0)
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    mrp = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    def __str__(self):
        return f"Draft Item: {self.raw_product_name} for INV: {self.draft_invoice.invoice_number}"
