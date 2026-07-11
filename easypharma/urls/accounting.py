from django.urls import path
from easypharma.views.accounting import (
    SupplierLedgerView, SupplierPaymentView, ExpiryReturnView, 
    StockBatchAutocomplete, SupplierCreditBillsView,
    DeleteSupplierPaymentView, DeleteExpiryReturnView,
    SupplierUnadjustedReturnsView,
    CustomerPaymentView, DeleteCustomerPaymentView, CustomerCreditBillsView
)

urlpatterns = [
    path('accounting/supplier-ledger/', SupplierLedgerView.as_view(), name='supplier_ledger'),
    path('accounting/supplier-payment/', SupplierPaymentView.as_view(), name='supplier_payment'),
    path('accounting/supplier-payment/<int:pk>/delete/', DeleteSupplierPaymentView.as_view(), name='delete_supplier_payment'),
    path('accounting/expiry-return/', ExpiryReturnView.as_view(), name='expiry_return'),
    path('accounting/expiry-return/<int:pk>/delete/', DeleteExpiryReturnView.as_view(), name='delete_expiry_return'),
    path('api/stock-batches/', StockBatchAutocomplete.as_view(), name='stock_batch_autocomplete'),
    path('api/supplier-credit-bills/', SupplierCreditBillsView.as_view(), name='supplier_credit_bills'),
    path('api/supplier-unadjusted-returns/', SupplierUnadjustedReturnsView.as_view(), name='supplier_unadjusted_returns'),
    
    # Customer Credit Accounting
    path('accounting/customer-payment/', CustomerPaymentView.as_view(), name='customer_payment'),
    path('accounting/customer-payment/<int:pk>/delete/', DeleteCustomerPaymentView.as_view(), name='delete_customer_payment'),
    path('api/customer-credit-bills/', CustomerCreditBillsView.as_view(), name='customer_credit_bills'),
]
