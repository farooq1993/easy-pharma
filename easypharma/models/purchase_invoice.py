from django.db import models
from tenants.models import TenantAwareModel
from easypharma.models.Items import Products
from easypharma.models.accounts import User
from django.db import transaction
import datetime
from django.utils import timezone

class Supplier(TenantAwareModel):
    name = models.CharField(max_length=200)
    contact_person = models.CharField(max_length=100, null=True, blank=True)
    phone = models.CharField(max_length=20)
    email = models.EmailField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    state = models.CharField(max_length=20, null=True, blank=True)
    gst_number = models.CharField(max_length=20, null=True, blank=True)
    dl_number = models.CharField(max_length=50, null=True, blank=True, help_text="Drug License Number")
    
    def __str__(self):
        return self.name

class PurchaseInvoice(TenantAwareModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, null=True, blank=True)
    invoice_number = models.CharField(max_length=100)
    purchase_date = models.DateField(null=True, blank=True)
    payment_mode = models.CharField(max_length=20, default='Cash', choices=[('Cash', 'Cash'), ('Credit', 'Credit')])
    
    voucher_number = models.CharField(max_length=30, blank=True, null=True, db_index=True)
    sub_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    @classmethod
    def generate_voucher_number(cls, tenant, purchase_date=None):
        """
        Sequential, tenant-scoped voucher number.
        Format: PV-YYYY-XXXXXX  e.g. PV-2026-000042
        Counter resets each financial year (April 1 – March 31).
        """
 
        today = purchase_date or timezone.now().date()
        if isinstance(today, str):
            today = datetime.date.fromisoformat(today)
 
        # Financial year starts April
        fy_year = today.year if today.month >= 4 else today.year - 1
        fy_start = datetime.date(fy_year, 4, 1)
        fy_end = datetime.date(fy_year + 1, 3, 31)
 
        last = (
            cls.objects
            .filter(
                tenant=tenant,
                purchase_date__range=(fy_start, fy_end),
                voucher_number__startswith=f"PV-{fy_year}-"
            )
            .order_by('-voucher_number')
            .first()
        )
        if last and last.voucher_number:
            try:
                last_seq = int(last.voucher_number.rsplit('-', 1)[-1])
            except ValueError:
                last_seq = 0
        else:
            last_seq = 0
 
        return f"PV-{fy_year}-{str(last_seq + 1).zfill(6)}"

    @property
    def balance(self):
        return self.total_amount - self.paid_amount
    
    def __str__(self):
        return f"Purchase INV: {self.invoice_number} from {self.supplier}"

class PurchaseItem(TenantAwareModel):
    purchase_invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Products, on_delete=models.CASCADE)
    batch_number = models.CharField(max_length=100)
    expiry_date = models.DateField()
    
    quantity = models.PositiveIntegerField()
    free_quantity = models.PositiveIntegerField(default=0)
    
    purchase_price = models.DecimalField(max_digits=10, decimal_places=2)
    mrp = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2)
    
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def save(self, *args, **kwargs):
        # When a purchase item is saved, we update the stock
        from easypharma.models.stock import StockBatch
        with transaction.atomic():
            super().save(*args, **kwargs)
            # Update or create stock batch
            total_units = (self.quantity + self.free_quantity) * self.product.conversion_factor
            
            batch, created = StockBatch.objects.get_or_create(
                tenant=self.tenant,
                product=self.product,
                batch_number=self.batch_number,
                defaults={
                    'expiry_date': self.expiry_date,
                    'purchase_price': self.purchase_price,
                    'mrp': self.mrp,
                    'sale_price': self.sale_price,
                    'initial_quantity': total_units,
                    'current_quantity': total_units
                }
            )
            if not created:
                batch.current_quantity += total_units
                batch.save()
