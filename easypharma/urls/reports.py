from django.urls import path
from easypharma.views.reports import StockReportView

urlpatterns = [
    path('stock/', StockReportView.as_view(), name='stock_report'),
]
