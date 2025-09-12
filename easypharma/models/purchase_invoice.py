from django.db import models
from easypharma.models.Items import Products
from easypharma.models.accounts import User

class PurchaseInvoice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    invoice_number = models.CharField(max_length=100, unique=True) 
    product = models.ForeignKey(Products, on_delete=models.CASCADE)
    product_batch_no = models.CharField(max_length=100)
    product_expiry_date = models.DateField()
    product_purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    product_mrp = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    product_schme_qty = models.PositiveIntegerField(null=True, blank=True)
    product_discount = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, null=True, blank=True)  # percentage
    product_total = models.DecimalField(max_digits=10, decimal_places=2,null=True, blank=True)
    total_bill_amount = models.DecimalField(max_digits=10, decimal_places=2,null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Purchase Invoice {self.invoice_number} - {self.user.username}"
    
    def save(self, *args, **kwargs):
        self.product_total = self.product_purchase_price * self.quantity 
        self.total_bill_amount = self.product_total
        super().save(*args, **kwargs)
