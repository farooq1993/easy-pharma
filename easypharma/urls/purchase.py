from django.urls import path
from easypharma.views.purchase import (PurchaseEntryView, PurchaseListView,
                                        SupplierAutocomplete, SupplierWisePurchaseReportView,
                                        SupplierReportDataView, PurchaseExportCSVView,
                                        PurchaseExportPDFView, PurchaseImportCSVView,
                                        QuickCreateProductView, ProductBatchHistoryView,SmartPurchaseSuggestPageView,
                                        SmartPurchaseSuggestAPIView,PurchaseEntryView,
                                        OpeningStockListView,OpeningStockEntryView)

urlpatterns = [
    path('entry/', PurchaseEntryView.as_view(), name='purchase_entry'),
    path('opening/stock/list', OpeningStockListView.as_view(), name='opening_stock'),
    path('opening/stock/entry', OpeningStockEntryView.as_view(), name='opening_stock_entry'),
    path('edit/<int:invoice_id>/', PurchaseEntryView.as_view(), name='purchase_edit'),
    path('list/', PurchaseListView.as_view(), name='purchase_list'),
    path('delete/<int:invoice_id>/', PurchaseListView.as_view(), name='purchase_delete'),
    path('api/suppliers/search/', SupplierAutocomplete.as_view(), name='supplier_search_api'),
    path('api/products/create-quick/', QuickCreateProductView.as_view(), name='quick_create_product'),
    path('report/supplier-wise/', SupplierWisePurchaseReportView.as_view(), name='supplier_wise_purchase_report'),
    path('supplier_report_data/<int:supplier_id>/', SupplierReportDataView.as_view(), name='supplier_report_data'),
    path('purchase/suggestions/', SmartPurchaseSuggestPageView.as_view(), name='smart_purchase_suggest_page'),
    path('purchase/suggestions/data/', SmartPurchaseSuggestAPIView.as_view(), name='smart_purchase_suggest'),

    # Export & Import
    path('export/csv/', PurchaseExportCSVView.as_view(), name='purchase_export_csv'),
    path('export/pdf/', PurchaseExportPDFView.as_view(), name='purchase_export_pdf'),
    path('import/csv/', PurchaseImportCSVView.as_view(), name='purchase_import_csv'),
    path('api/products/batch-history/', ProductBatchHistoryView.as_view(), name='batch_history'),
]
