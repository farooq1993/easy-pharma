from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.utils import timezone
from easypharma.models.financial_year import FinancialYear
from easypharma.utility.fy_helper import get_or_create_financial_year, get_financial_year_dates
from datetime import date, datetime


class FinancialYearView(LoginRequiredMixin, View):
    template_name = 'utility/financial_year.html'

    def get(self, request):
        # Ensure current financial year exists
        current_fy = get_or_create_financial_year(request.tenant)
        
        # Get all financial years for this tenant
        fy_list = FinancialYear.objects.filter(tenant=request.tenant).order_by('-start_date')
        
        return render(request, self.template_name, {
            'current_fy': current_fy,
            'fy_list': fy_list,
        })

    def post(self, request):
        action = request.POST.get('action')
        fy_id = request.POST.get('fy_id')
        notes = request.POST.get('notes', '')

        if action == 'toggle_lock' and fy_id:
            fy = get_object_or_404(FinancialYear, id=fy_id, tenant=request.tenant)
            if fy.is_locked:
                fy.is_locked = False
                fy.notes = notes
                fy.save(update_fields=['is_locked', 'notes', 'updated_at'])
                messages.success(request, f"Financial Year {fy.fy_code} has been UNLOCKED successfully.")
            else:
                fy.is_locked = True
                fy.locked_at = timezone.now()
                fy.locked_by = request.user
                fy.notes = notes
                fy.save(update_fields=['is_locked', 'locked_at', 'locked_by', 'notes', 'updated_at'])
                messages.warning(request, f"Financial Year {fy.fy_code} is now LOCKED (Frozen). Books are sealed for this period.")

        elif action == 'create_fy':
            start_date_str = request.POST.get('start_date')
            if start_date_str:
                try:
                    s_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                    get_or_create_financial_year(request.tenant, s_date)
                    messages.success(request, "Financial Year created successfully.")
                except Exception as e:
                    messages.error(request, f"Failed to create Financial Year: {str(e)}")

        return redirect('financial_year_management')
