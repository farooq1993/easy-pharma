from django.urls import path
from easypharma.views.purchase import (PurchaseEntryView, PurchaseListView,
                                        SupplierAutocomplete, SupplierWisePurchaseReportView,
                                        SupplierReportDataView, PurchaseExportCSVView,
                                        PurchaseExportPDFView)

urlpatterns = [
    path('entry/', PurchaseEntryView.as_view(), name='purchase_entry'),
    path('edit/<int:invoice_id>/', PurchaseEntryView.as_view(), name='purchase_edit'),
    path('list/', PurchaseListView.as_view(), name='purchase_list'),
    path('delete/<int:invoice_id>/', PurchaseListView.as_view(), name='purchase_delete'),
    path('api/suppliers/search/', SupplierAutocomplete.as_view(), name='supplier_search_api'),
    path('report/supplier-wise/', SupplierWisePurchaseReportView.as_view(), name='supplier_wise_purchase_report'),
    path('supplier_report_data/<int:supplier_id>/', SupplierReportDataView.as_view(), name='supplier_report_data'),

    # Export
    path('export/csv/', PurchaseExportCSVView.as_view(), name='purchase_export_csv'),
    path('export/pdf/', PurchaseExportPDFView.as_view(), name='purchase_export_pdf'),
]
