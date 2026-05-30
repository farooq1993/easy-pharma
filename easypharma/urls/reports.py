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
)

urlpatterns = [
    path('stock/', StockReportView.as_view(), name='stock_report'),
    
    # New Reports
    path('daily-sales/', DailySaleReportView.as_view(), name='daily_sale_report'),
    path('half-yearly-sales/', HalfYearlySaleReportView.as_view(), name='half_yearly_report'),
    path('profit/', ProfitReportView.as_view(), name='profit_report'),
    path('gst/', GSTReportView.as_view(), name='gst_report'),
    path('product-history/', ProductHistoryView.as_view(), name='product_history'),

    # Drug Register Reports
    path('schedule-h/', ScheduleHReportView.as_view(), name='schedule_h_report'),
    path('narcotic-drug/', NarcoticDrugReportView.as_view(), name='narcotic_drug_report'),
]
