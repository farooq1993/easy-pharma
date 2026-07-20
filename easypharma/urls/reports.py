from django.urls import path
from easypharma.views.reports import (
    StockReportView,
    DailySaleReportView,
    HalfYearlySaleReportView,
    ProfitReportView,
    GSTReportView,
    ProductHistoryView,
    ScheduleHReportView,
    NarcoticDrugReportView,
    ScheduleH1PurchaseReportView,
    GSTR3BReportView,
    GSTR1ReportView,
    PurchaseAnalysisView,
    SaleBillWiseProfit,
    SalesReturnReportView,
    DoctorSaleReportView,
)

urlpatterns = [
    path('stock/', StockReportView.as_view(), name='stock_report'),
    
    # New Reports
    path('daily-sales/', DailySaleReportView.as_view(), name='daily_sale_report'),
    path('doctor-sales/', DoctorSaleReportView.as_view(), name='doctor_sale_report'),
    path('half-yearly-sales/', HalfYearlySaleReportView.as_view(), name='half_yearly_report'),
    path('profit/', ProfitReportView.as_view(), name='profit_report'),
    path('bill-wise-profit/', SaleBillWiseProfit.as_view(), name='bill_wise_profit_report'),
    path('gst/', GSTReportView.as_view(), name='gst_report'),
    path('product-history/', ProductHistoryView.as_view(), name='product_history'),
    path('sales-return/', SalesReturnReportView.as_view(), name='sales_return_report'),

    # Drug Register Reports
    path('schedule-h/', ScheduleHReportView.as_view(), name='schedule_h_report'),
    path('narcotic-drug/', NarcoticDrugReportView.as_view(), name='narcotic_drug_report'),
    path('schedule-h1-purchase/', ScheduleH1PurchaseReportView.as_view(), name='schedule_h1_purchase_report'),

    # GST Compliance Reports
    path('gstr3b/', GSTR3BReportView.as_view(), name='gstr3b_report'),
    path('gstr1/', GSTR1ReportView.as_view(), name='gstr1_report'),

    # Purchase Analysis
    path('purchase-analysis/', PurchaseAnalysisView.as_view(), name='purchase_analysis'),
]
