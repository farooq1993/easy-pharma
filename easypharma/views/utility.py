from django.views import View
from django.shortcuts import render
from easypharma.models.stock import StockBatch
from datetime import date, timedelta

class UtilityHomeView(View):
    template_name = 'utility/home.html'

    def get(self, request):
        today = date.today()
        # Full expiry report logic
        expiry_6_months = today + timedelta(days=180)
        expiring_batches = StockBatch.objects.filter(
            tenant=request.tenant,
            expiry_date__lte=expiry_6_months,
            current_quantity__gt=0
        ).select_related('product').order_by('expiry_date')
        
        return render(request, self.template_name, {
            'expiring_batches': expiring_batches,
        })

class PrintingSetupView(View):
    template_name = 'utility/printing.html'

    def get(self, request):
        return render(request, self.template_name)
