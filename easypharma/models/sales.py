from django.db import models
from tenants.models import TenantAwareModel
from easypharma.models.Items import Products
from django.conf import settings
from django.db import transaction

class Customer(TenantAwareModel):
    name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class SaleInvoice(TenantAwareModel):
    invoice_number = models.CharField(max_length=50, unique=True)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    patient_name = models.CharField(max_length=200, null=True, blank=True)
    patient_address = models.CharField(max_length=200, null=True, blank=True)
    patient_phone = models.CharField(max_length=20, null=True, blank=True)
    doctor_name = models.CharField(max_length=200, null=True, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sub_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    payment_mode = models.CharField(max_length=50, choices=[('Cash', 'Cash'), ('Card', 'Card'), ('UPI', 'UPI'), ('Credit', 'Credit')], default='Cash')
    sale_type = models.CharField(max_length=50, choices=[('Prescription', 'Prescription Sale'), ('Counter', 'Counter Sale')], default='Prescription')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.invoice_number

class SaleItem(TenantAwareModel):
    sale_invoice = models.ForeignKey(SaleInvoice, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Products, on_delete=models.CASCADE)
    batch_number = models.CharField(max_length=50, null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    tax_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    discount_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product.product_name} - {self.quantity}"


class SalesReturn(TenantAwareModel):
    return_inv_no = models.CharField(max_length=50, unique=True)
    sale_invoice = models.ForeignKey(SaleInvoice, on_delete=models.CASCADE, related_name='sales_return')
    return_qty = models.IntegerField()
    return_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    return_at = models.DateTimeField(auto_now_add=True)


    def save(self, *args, **kwargs):

        if not self.return_inv_no:

            with transaction.atomic():

                last_return = (
                    SalesReturn.objects
                    .select_for_update()
                    .filter(tenant=self.tenant)
                    .order_by('-id')
                    .first()
                )

                if last_return and last_return.return_inv_no:

                    try:
                        last_number = int(
                            last_return.return_inv_no.split('-')[-1]
                        )

                    except (ValueError, IndexError):
                        last_number = 0

                else:
                    last_number = 0

                new_number = last_number + 1

                self.return_inv_no = (
                    f"SR-{self.tenant.id}-{new_number:04d}"
                )

                super().save(*args, **kwargs)

        else:
            super().save(*args, **kwargs)
    

    def __str__(self):
        return self.sale_invoice.customer


class SalesReturnItem(TenantAwareModel):
    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name='return_items')
    sale_item = models.ForeignKey(SaleItem, on_delete=models.CASCADE)
    returned_quantity = models.PositiveIntegerField()
    return_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Return of {self.returned_quantity} x {self.sale_item.product.product_name}"

    def save(self, *args, **kwargs):
        # Ensure returned quantity doesn't exceed sold quantity
        if self.returned_quantity > self.sale_item.quantity:
            raise ValueError("Returned quantity cannot exceed sold quantity")
        super().save(*args, **kwargs)

class PrescriptionReminder(TenantAwareModel):
    patient_name = models.CharField(max_length=255)

    prescription_date = models.DateField()
    reminder_date = models.DateField()
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reminder for {self.patient_name} on {self.reminder_date}"