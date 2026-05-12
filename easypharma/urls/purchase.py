from django.urls import path
from easypharma.views.purchase import PurchaseEntryView, PurchaseListView, SupplierAutocomplete

urlpatterns = [
    path('entry/', PurchaseEntryView.as_view(), name='purchase_entry'),
    path('list/', PurchaseListView.as_view(), name='purchase_list'),
    path('delete/<int:invoice_id>/', PurchaseListView.as_view(), name='purchase_delete'),
    path('api/suppliers/search/', SupplierAutocomplete.as_view(), name='supplier_search_api'),
]
