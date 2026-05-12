from django.views import View
from django.shortcuts import render
from easypharma.models.stock import StockBatch
from easypharma.models.Items import Products
from django.db.models import Sum, F

class StockReportView(View):
    template_name = 'reports/stock_report.html'

    def get(self, request):
        # Aggregate stock by product
        stocks = StockBatch.objects.filter(tenant=request.tenant, current_quantity__gt=0).select_related('product')
        
        # Also group by product for a summary
        product_summary = StockBatch.objects.filter(tenant=request.tenant).values(
            'product__product_name', 'product__product_packing'
        ).annotate(
            total_stock=Sum('current_quantity'),
            total_value=Sum(F('current_quantity') * F('purchase_price'))
        ).order_by('product__product_name')

        return render(request, self.template_name, {
            'stocks': stocks,
            'summary': product_summary
        })
