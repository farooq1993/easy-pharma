from django.urls import path
from easypharma.views.sales import(POSView, ProductSearchAPI, 
                        SaleListView, PrintInvoiceView, 
                        SalesReturnView, SubstituteSearchAPI,PatientWiseSales,PatientWiseSalesAPI,PrescriptionReminderView,
                        get_customer_invoices,PrescriptionReminderDeleteView)

urlpatterns = [
    path('pos/', POSView.as_view(), name='pos'),
    path('pos/edit/<int:invoice_id>/', POSView.as_view(), name='pos_edit'),
    path('pos/list/', SaleListView.as_view(), name='pos_list'),
    path('pos/delete/<int:invoice_id>/', SaleListView.as_view(), name='pos_delete'),
    path('pos/print/<int:invoice_id>/', PrintInvoiceView.as_view(), name='pos_print'),
    path('pos/returns/', SalesReturnView.as_view(), name='pos_returns'),
    path('api/products/search/', ProductSearchAPI.as_view(), name='product_search_api'),
    path('api/products/substitute/', SubstituteSearchAPI.as_view(), name='substitute_search_api'),
    path('sales/patient-wise/', PatientWiseSales.as_view(), name='patient_wise_sales'),
    path('api/sales/patient-wise/', PatientWiseSalesAPI.as_view(), name='patient_wise_sales_api'),
    path('sales/prescription-reminders/', PrescriptionReminderView.as_view(), name='prescription_reminders'),
    path('sales/prescription-reminders/delete/<int:reminder_id>/',PrescriptionReminderDeleteView.as_view(),name='delete_prescription_reminder'),
    path('sales/get-customer-invoices/',get_customer_invoices,name='get_customer_invoices')
]
