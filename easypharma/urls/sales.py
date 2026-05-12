from django.urls import path
from easypharma.views.sales import POSView, ProductSearchAPI, SaleListView, PrintInvoiceView

urlpatterns = [
    path('pos/', POSView.as_view(), name='pos'),
    path('pos/list/', SaleListView.as_view(), name='pos_list'),
    path('pos/delete/<int:invoice_id>/', SaleListView.as_view(), name='pos_delete'),
    path('pos/print/<int:invoice_id>/', PrintInvoiceView.as_view(), name='pos_print'),
    path('api/products/search/', ProductSearchAPI.as_view(), name='product_search_api'),
]
