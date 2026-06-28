from django.db import models
from tenants.models import TenantAwareModel
from .purchase_invoice import Supplier, PurchaseInvoice
from .Items import Products

class SupplierLedger(TenantAwareModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='ledger_entries')
    date = models.DateField()
    transaction_type = models.CharField(max_length=50, choices=[('Purchase', 'Purchase'), ('Payment', 'Payment'), ('Return', 'Return')])
    reference_number = models.CharField(max_length=100, null=True, blank=True)
    debit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00) # Payment to supplier, Return
    credit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00) # Purchase from supplier
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_adjusted = models.BooleanField(default=False)
    remarks = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"{self.supplier.name} - {self.transaction_type} on {self.date}"

class SupplierPayment(TenantAwareModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='payments')
    payment_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_mode = models.CharField(max_length=50, choices=[('Cash', 'Cash'), ('Bank', 'Bank'), ('Cheque', 'Cheque')])
    reference_number = models.CharField(max_length=100, null=True, blank=True)
    payment_details = models.JSONField(null=True, blank=True) # To store bank/cheque info and adjusted invoices
    remarks = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Payment to {self.supplier.name} on {self.payment_date} - {self.amount}"

class ExpiryReturn(TenantAwareModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name='expiry_returns')
    return_date = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    return_details = models.JSONField(null=True, blank=True)
    remarks = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Expiry Return to {self.supplier.name} on {self.return_date}"

class ExpiryReturnItem(TenantAwareModel):
    expiry_return = models.ForeignKey(ExpiryReturn, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Products, on_delete=models.CASCADE)
    batch_number = models.CharField(max_length=100)
    quantity = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=10, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product.name} - {self.batch_number} (x{self.quantity})"

# --- General Accounting Models ---

class AccountGroup(TenantAwareModel):
    name = models.CharField(max_length=100)
    nature = models.CharField(max_length=50, choices=[
        ('Asset', 'Asset'),
        ('Liability', 'Liability'),
        ('Income', 'Income'),
        ('Expense', 'Expense')
    ])

    def __str__(self):
        return self.name

class LedgerAccount(TenantAwareModel):
    name = models.CharField(max_length=200)
    group = models.ForeignKey(AccountGroup, on_delete=models.CASCADE, related_name='accounts')
    opening_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    balance_type = models.CharField(max_length=10, choices=[('Dr', 'Debit'), ('Cr', 'Credit')], default='Dr')

    def __str__(self):
        return self.name

class Voucher(TenantAwareModel):
    voucher_type = models.CharField(max_length=50, choices=[
        ('Receipt', 'Receipt'),
        ('Payment', 'Payment'),
        ('Contra', 'Contra'),
        ('Journal', 'Journal')
    ])
    voucher_number = models.CharField(max_length=50)
    date = models.DateField()
    narration = models.TextField(null=True, blank=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.voucher_type} - {self.voucher_number}"

class VoucherEntry(TenantAwareModel):
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE, related_name='entries')
    account = models.ForeignKey(LedgerAccount, on_delete=models.CASCADE)
    entry_type = models.CharField(max_length=10, choices=[('Dr', 'Debit'), ('Cr', 'Credit')])
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.account.name} - {self.entry_type} {self.amount}"
