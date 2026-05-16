from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse_lazy
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.utils import timezone
from datetime import datetime, timedelta
import json

from easypharma.models.gst import (
    GSTConfiguration, GSTFiling, GSTReturn, GSTCompositionReturn, 
    GSTReminder, GSTScheme
)


class GSTDashboardView(LoginRequiredMixin, TemplateView):
    """Dashboard for GST filing overview"""
    template_name = 'gst/gst_dashboard.html'
    login_url = 'login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get GST configuration for this tenant
        gst_config = GSTConfiguration.objects.filter(tenant=self.request.tenant).first()
        context['gst_config'] = gst_config
        
        if gst_config:
            # Get all filings
            filings = GSTFiling.objects.filter(gst_config=gst_config).order_by('-period_start')
            context['filings'] = filings
            
            # Get upcoming due dates
            today = timezone.now().date()
            upcoming = filings.filter(due_date__gte=today, status__in=['draft', 'prepared']).order_by('due_date')
            context['upcoming_filings'] = upcoming[:5]
            
            # Get overdue filings
            overdue = filings.filter(due_date__lt=today, status__in=['draft', 'prepared'])
            context['overdue_filings'] = overdue
            
            # Statistics
            context['total_filings'] = filings.count()
            context['filed_filings'] = filings.filter(status__in=['filed', 'accepted']).count()
            context['pending_filings'] = filings.filter(status__in=['draft', 'prepared']).count()
            context['rejected_filings'] = filings.filter(status='rejected').count()
        
        return context


class GSTConfigurationView(LoginRequiredMixin, TemplateView):
    """View and manage GST configuration"""
    template_name = 'gst/gst_configuration.html'
    login_url = 'login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        gst_config = GSTConfiguration.objects.filter(tenant=self.request.tenant).first()
        context['gst_config'] = gst_config
        context['schemes'] = GSTScheme.objects.all()
        return context

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            gst_config, created = GSTConfiguration.objects.update_or_create(
                tenant=request.tenant,
                defaults={
                    'scheme': data.get('scheme', 'regular'),
                    'gst_number': data.get('gst_number'),
                    'legal_name': data.get('legal_name'),
                    'trade_name': data.get('trade_name'),
                    'filing_frequency': data.get('filing_frequency', 'monthly'),
                }
            )
            return JsonResponse({'success': True, 'id': gst_config.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class GSTFilingListView(LoginRequiredMixin, ListView):
    """List all GST filings for current tenant"""
    model = GSTFiling
    template_name = 'gst/gst_filing_list.html'
    context_object_name = 'filings'
    login_url = 'login/'
    paginate_by = 20

    def get_queryset(self):
        gst_config = GSTConfiguration.objects.filter(tenant=self.request.tenant).first()
        if gst_config:
            return GSTFiling.objects.filter(gst_config=gst_config).order_by('-period_start')
        return GSTFiling.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['gst_config'] = GSTConfiguration.objects.filter(tenant=self.request.tenant).first()
        return context


class GSTFilingDetailView(LoginRequiredMixin, DetailView):
    """View details of a specific GST filing"""
    model = GSTFiling
    template_name = 'gst/gst_filing_detail.html'
    context_object_name = 'filing'
    login_url = 'login/'

    def get_queryset(self):
        return GSTFiling.objects.filter(gst_config__tenant=self.request.tenant)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filing = self.get_object()
        
        # Get return details
        if filing.form_type in ['gstr-1', 'gstr-3b', 'gstr-9']:
            context['return_details'] = GSTReturn.objects.filter(gst_filing=filing).first()
        else:  # Composition scheme
            context['return_details'] = GSTCompositionReturn.objects.filter(gst_filing=filing).first()
        
        # Get reminders
        context['reminders'] = GSTReminder.objects.filter(gst_filing=filing).order_by('reminder_date')
        
        return context


class GSTFilingCreateView(LoginRequiredMixin, CreateView):
    """Create a new GST filing"""
    model = GSTFiling
    template_name = 'gst/gst_filing_form.html'
    fields = ['form_type', 'period_start', 'period_end', 'due_date']
    login_url = 'login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['gst_config'] = GSTConfiguration.objects.filter(tenant=self.request.tenant).first()
        return context

    def form_valid(self, form):
        gst_config = GSTConfiguration.objects.filter(tenant=self.request.tenant).first()
        if not gst_config:
            messages.error(self.request, 'GST Configuration not set. Please configure GST first.')
            return self.form_invalid(form)
        
        form.instance.gst_config = gst_config
        messages.success(self.request, f'GST Filing {form.cleaned_data["form_type"]} created successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('gst_filing_detail', kwargs={'pk': self.object.pk})


class GSTFilingUpdateView(LoginRequiredMixin, UpdateView):
    """Update a GST filing"""
    model = GSTFiling
    template_name = 'gst/gst_filing_form.html'
    fields = ['form_type', 'period_start', 'period_end', 'due_date', 'status', 'filed_on', 'acknowledgement_number']
    login_url = 'login/'

    def get_queryset(self):
        return GSTFiling.objects.filter(gst_config__tenant=self.request.tenant)

    def form_valid(self, form):
        messages.success(self.request, 'GST Filing updated successfully.')
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('gst_filing_detail', kwargs={'pk': self.object.pk})


class GSTFilingDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a GST filing"""
    model = GSTFiling
    template_name = 'gst/gst_filing_confirm_delete.html'
    success_url = reverse_lazy('gst_filing_list')
    login_url = 'login/'

    def get_queryset(self):
        return GSTFiling.objects.filter(gst_config__tenant=self.request.tenant)

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'GST Filing deleted successfully.')
        return super().delete(request, *args, **kwargs)


class GSTReturnDetailView(LoginRequiredMixin, TemplateView):
    """View detailed breakdown of GST return"""
    template_name = 'gst/gst_return_detail.html'
    login_url = 'login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filing_id = self.kwargs.get('filing_id')
        
        filing = get_object_or_404(GSTFiling, id=filing_id, gst_config__tenant=self.request.tenant)
        context['filing'] = filing
        
        if filing.form_type in ['gstr-1', 'gstr-3b', 'gstr-9']:
            context['return'] = GSTReturn.objects.filter(gst_filing=filing).first()
        else:
            context['return'] = GSTCompositionReturn.objects.filter(gst_filing=filing).first()
        
        return context


class GSTReturnUpdateView(LoginRequiredMixin, TemplateView):
    """Update GST return details"""
    template_name = 'gst/gst_return_form.html'
    login_url = 'login/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        filing_id = self.kwargs.get('filing_id')
        filing = get_object_or_404(GSTFiling, id=filing_id, gst_config__tenant=self.request.tenant)
        context['filing'] = filing
        
        if filing.form_type in ['gstr-1', 'gstr-3b', 'gstr-9']:
            context['return'] = GSTReturn.objects.filter(gst_filing=filing).first()
        else:
            context['return'] = GSTCompositionReturn.objects.filter(gst_filing=filing).first()
        
        return context

    def post(self, request, *args, **kwargs):
        try:
            filing_id = self.kwargs.get('filing_id')
            filing = get_object_or_404(GSTFiling, id=filing_id, gst_config__tenant=request.tenant)
            data = json.loads(request.body)
            
            if filing.form_type in ['gstr-1', 'gstr-3b', 'gstr-9']:
                # Update regular return
                return_obj, created = GSTReturn.objects.update_or_create(
                    gst_filing=filing,
                    defaults={
                        'intrastate_supply': data.get('intrastate_supply', 0),
                        'interstate_supply': data.get('interstate_supply', 0),
                        'exempt_supply': data.get('exempt_supply', 0),
                        'cgst_5pct': data.get('cgst_5pct', 0),
                        'sgst_5pct': data.get('sgst_5pct', 0),
                        'igst_5pct': data.get('igst_5pct', 0),
                        'cgst_12pct': data.get('cgst_12pct', 0),
                        'sgst_12pct': data.get('sgst_12pct', 0),
                        'igst_12pct': data.get('igst_12pct', 0),
                        'cgst_18pct': data.get('cgst_18pct', 0),
                        'sgst_18pct': data.get('sgst_18pct', 0),
                        'igst_18pct': data.get('igst_18pct', 0),
                    }
                )
            else:
                # Update composition return
                return_obj, created = GSTCompositionReturn.objects.update_or_create(
                    gst_filing=filing,
                    defaults={
                        'total_turnover': data.get('total_turnover', 0),
                        'composition_tax_rate': data.get('composition_tax_rate', 1),
                        'composition_tax_liability': data.get('composition_tax_liability', 0),
                    }
                )
            
            return JsonResponse({'success': True, 'id': return_obj.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class GSTReminderListView(LoginRequiredMixin, ListView):
    """View GST filing reminders"""
    model = GSTReminder
    template_name = 'gst/gst_reminder_list.html'
    context_object_name = 'reminders'
    login_url = 'login/'
    paginate_by = 20

    def get_queryset(self):
        gst_config = GSTConfiguration.objects.filter(tenant=self.request.tenant).first()
        if gst_config:
            filings = GSTFiling.objects.filter(gst_config=gst_config)
            return GSTReminder.objects.filter(gst_filing__in=filings).order_by('reminder_date')
        return GSTReminder.objects.none()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        qs = self.get_queryset()
        context['upcoming_count'] = qs.filter(reminder_date__gte=today).count()
        context['overdue_count'] = qs.filter(reminder_date__lt=today, is_notified=False).count()
        return context


class GSTAPIView(LoginRequiredMixin, TemplateView):
    """API endpoints for GST operations"""
    login_url = 'login/'

    def get(self, request, *args, **kwargs):
        action = request.GET.get('action')
        
        if action == 'filing_list':
            gst_config = GSTConfiguration.objects.filter(tenant=request.tenant).first()
            if gst_config:
                filings = GSTFiling.objects.filter(gst_config=gst_config).values(
                    'id', 'form_type', 'period_start', 'period_end', 'status', 'due_date'
                )
                return JsonResponse(list(filings), safe=False)
        
        return JsonResponse({'error': 'Invalid action'}, status=400)

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            action = data.get('action')
            
            if action == 'mark_filed':
                filing = get_object_or_404(GSTFiling, id=data.get('filing_id'), gst_config__tenant=request.tenant)
                filing.status = 'filed'
                filing.filed_on = timezone.now()
                filing.acknowledgement_number = data.get('acknowledgement_number')
                filing.reference_number = data.get('reference_number')
                filing.save()
                messages.success(request, f'Filing {filing.form_type} marked as filed.')
                return JsonResponse({'success': True})
            
            elif action == 'mark_accepted':
                filing = get_object_or_404(GSTFiling, id=data.get('filing_id'), gst_config__tenant=request.tenant)
                filing.status = 'accepted'
                filing.save()
                return JsonResponse({'success': True})
            
            elif action == 'create_reminders':
                filing = get_object_or_404(GSTFiling, id=data.get('filing_id'), gst_config__tenant=request.tenant)
                
                # Create reminders: 7 days before due date and on due date
                reminder_dates = [
                    (filing.due_date - timedelta(days=7), 'due_date'),
                    (filing.due_date, 'due_date'),
                ]
                
                for reminder_date, reminder_type in reminder_dates:
                    GSTReminder.objects.get_or_create(
                        gst_filing=filing,
                        tenant=request.tenant,
                        reminder_date=reminder_date,
                        reminder_type=reminder_type,
                    )
                
                return JsonResponse({'success': True, 'message': 'Reminders created'})
        
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
