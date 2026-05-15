import json
import base64
from django.views import View
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from easypharma.models.stock import StockBatch
from easypharma.models.print_setup import PrintSetup
from datetime import date, timedelta


class UtilityHomeView(View):
    template_name = 'utility/home.html'

    def get(self, request):
        today = date.today()
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
        setup, _ = PrintSetup.objects.get_or_create(tenant=request.tenant)
        return render(request, self.template_name, {'setup': setup})

    def post(self, request):
        setup, _ = PrintSetup.objects.get_or_create(tenant=request.tenant)

        # Paper settings
        setup.paper_size = request.POST.get('paper_size', 'A4')
        setup.margin_top = int(request.POST.get('margin_top', 10))
        setup.margin_sides = int(request.POST.get('margin_sides', 10))

        # Content toggles
        setup.show_logo = request.POST.get('show_logo') == 'on'
        setup.show_gst_details = request.POST.get('show_gst_details') == 'on'
        setup.show_dl_details = request.POST.get('show_dl_details') == 'on'
        setup.show_customer_signature = request.POST.get('show_customer_signature') == 'on'
        setup.show_pharmacist_signature = request.POST.get('show_pharmacist_signature') == 'on'

        # Custom text
        setup.custom_header = request.POST.get('custom_header', '').strip() or None
        setup.custom_footer = request.POST.get('custom_footer', '').strip() or None

        # Logo upload (convert to base64)
        logo_file = request.FILES.get('logo_file')
        if logo_file:
            # Validate file type
            if logo_file.content_type in ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp']:
                logo_data = base64.b64encode(logo_file.read()).decode('utf-8')
                setup.logo_base64 = f"data:{logo_file.content_type};base64,{logo_data}"
            else:
                messages.error(request, 'Invalid file type. Please upload PNG, JPG, or GIF.')
                return redirect('printing_setup')

        # Option to clear logo
        if request.POST.get('clear_logo') == 'yes':
            setup.logo_base64 = None

        setup.save()
        messages.success(request, 'Print settings saved successfully!')
        return redirect('printing_setup')
