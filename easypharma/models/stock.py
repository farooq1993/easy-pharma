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

    @property
    def is_expired(self):
        from django.utils.timezone import now
        today = now().date()
        if not self.expiry_date:
            return False
        # Under Indian pharmacy rules, a medicine with expiry MM/YY is valid until the last day of that month.
        # It is considered expired starting the 1st day of the next month.
        if self.expiry_date.month == 12:
            next_month_start = self.expiry_date.replace(year=self.expiry_date.year + 1, month=1, day=1)
        else:
            next_month_start = self.expiry_date.replace(month=self.expiry_date.month + 1, day=1)
        return today >= next_month_start

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
