from django.db import models
from tenants.models import TenantAwareModel
from easypharma.models.Items import Products
from django.utils import timezone

class StockBatch(TenantAwareModel):
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name='batches')
    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField()
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    initial_quantity = models.PositiveIntegerField()
    current_quantity = models.PositiveIntegerField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.product.product_name} - {self.batch_number} ({self.current_quantity} left)"

    class Meta:
        verbose_name_plural = "Stock Batches"
        unique_together = ('tenant', 'product', 'batch_number')


class StockDiscard(TenantAwareModel):
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name='discards')
    batch_number = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField(help_text="Quantity in units (e.g. strips/bottles/tablets)")
    discard_date = models.DateField(default=timezone.now)
    remarks = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Discard: {self.product.product_name} - {self.batch_number} ({self.quantity} units)"

    class Meta:
        verbose_name_plural = "Stock Discards"
