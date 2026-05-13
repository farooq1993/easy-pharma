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
        from django.db.models import ExpressionWrapper, DecimalField
        product_summary = StockBatch.objects.filter(tenant=request.tenant).values(
            'product__product_name', 'product__product_packing', 'product__conversion_factor'
        ).annotate(
            total_stock=Sum('current_quantity'),
            total_value=Sum(
                ExpressionWrapper(
                    F('current_quantity') * (F('purchase_price') / F('product__conversion_factor')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        ).order_by('product__product_name')

        total_value = sum(item['total_value'] for item in product_summary)
        
        return render(request, self.template_name, {
            'stocks': stocks,
            'summary': product_summary,
            'total_value': total_value
        })
