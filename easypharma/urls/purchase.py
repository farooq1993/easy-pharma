from django.urls import path
from easypharma.views.purchase import (PurchaseEntryView, PurchaseListView,
                                        SupplierAutocomplete, SupplierWisePurchaseReportView,
                                        SupplierReportDataView, PurchaseExportCSVView,
                                        PurchaseExportPDFView, PurchaseImportCSVView,
                                        QuickCreateProductView, ProductBatchHistoryView,SmartPurchaseSuggestPageView,
                                        SmartPurchaseSuggestAPIView,PurchaseEntryView,
                                        OpeningStockListView,OpeningStockEntryView,OpeningStockEditView,CheckInvoiceNumberView,OpeningStockDeleteView,
                                        GmailSyncConfigView, DraftPurchaseListView, DraftPurchaseSyncAPI, DraftPurchaseVerifyView, DraftPurchaseDeleteView)

urlpatterns = [
    path('entry/', PurchaseEntryView.as_view(), name='purchase_entry'),
    path('list/', PurchaseListView.as_view(), name='purchase_list'),
    path('edit/<int:invoice_id>/', PurchaseEntryView.as_view(), name='purchase_edit'),
    path('delete/<int:invoice_id>/', PurchaseListView.as_view(), name='purchase_delete'),

    path('opening/stock/list', OpeningStockListView.as_view(), name='opening_stock'),
    path('opening/stock/entry/', OpeningStockEntryView.as_view(), name='opening_stock_entry'),
    path('opening/stock/edit/<int:stock_id>/', OpeningStockEditView.as_view(), name='opening_stock_edit'),
    path('opening-stock/delete/<int:stock_id>/', OpeningStockDeleteView.as_view(), name='opening_stock_delete'),

    
    path('api/suppliers/search/', SupplierAutocomplete.as_view(), name='supplier_search_api'),
    path('api/products/create-quick/', QuickCreateProductView.as_view(), name='quick_create_product'),
    path('report/supplier-wise/', SupplierWisePurchaseReportView.as_view(), name='supplier_wise_purchase_report'),
    path('purchase/check-invoice-number/', CheckInvoiceNumberView.as_view(), name='check_invoice_number'),
    path('supplier_report_data/<int:supplier_id>/', SupplierReportDataView.as_view(), name='supplier_report_data'),
    path('purchase/suggestions/', SmartPurchaseSuggestPageView.as_view(), name='smart_purchase_suggest_page'),
    path('purchase/suggestions/data/', SmartPurchaseSuggestAPIView.as_view(), name='smart_purchase_suggest'),

    # Export & Import
    # Draft / Gmail sync URLs
    path('gmail-sync-config/', GmailSyncConfigView.as_view(), name='gmail_sync_config'),
    path('drafts/', DraftPurchaseListView.as_view(), name='draft_purchase_list'),
    path('drafts/sync/', DraftPurchaseSyncAPI.as_view(), name='draft_purchase_sync'),
    path('drafts/verify/<int:draft_id>/', DraftPurchaseVerifyView.as_view(), name='draft_purchase_verify'),
    path('drafts/delete/<int:draft_id>/', DraftPurchaseDeleteView.as_view(), name='draft_purchase_delete'),

    path('export/csv/', PurchaseExportCSVView.as_view(), name='purchase_export_csv'),
    path('export/pdf/', PurchaseExportPDFView.as_view(), name='purchase_export_pdf'),
    path('import/csv/', PurchaseImportCSVView.as_view(), name='purchase_import_csv'),
    path('api/products/batch-history/', ProductBatchHistoryView.as_view(), name='batch_history'),
]
