from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
import json
from django.core.paginator import Paginator
from django.apps import apps
from django.db.models import Q
from datetime import date
from easypharma.models.Items import (DrugCompany, ProductContent, 
                                     ProductSchedule,
                                     ProductTax, ProductType, Products)
from easypharma.models.purchase_invoice import Supplier

class MasterCRUDView(LoginRequiredMixin,View):
    """
    Generic view to handle CRUD for all master models.
    """
    http_method_names = ['get', 'post', 'patch', 'delete']

    def dispatch(self, request, *args, **kwargs):
        if 'master_type' in kwargs:
            kwargs['master_type'] = kwargs['master_type'].lower()
        return super().dispatch(request, *args, **kwargs)
    
    def get_model(self, master_type):
        models_map = {
            'product-type': ProductType,
            'drug-schedule': ProductSchedule,
            'product-tax': ProductTax,
            'product-content': ProductContent,
            'drug-company': DrugCompany,
            'drug-supplier': Supplier,
            'pharmacy-link': apps.get_model('tenants', 'Tenant'),
        }
        return models_map.get(master_type)

    def get_context_data(self, master_type):
        titles = {
            'product-type': 'Product Types',
            'drug-schedule': 'Drug Schedules',
            'product-tax': 'Product Taxes',
            'product-content': 'Product Contents',
            'drug-company': 'Drug Companies',
            'drug-supplier': 'Suppliers',
            'pharmacy-link': 'Firm/Pharmacy Details',
        }
        fields = {
            'product-type': [{'name': 'name', 'label': 'Type Name', 'type': 'text'}],
            'drug-schedule': [{'name': 'schedule_name', 'label': 'Schedule Name', 'type': 'text'}],
            'product-tax': [
                {'name': 'tax_name', 'label': 'Tax Name', 'type': 'text'},
                {'name': 'tax_rate', 'label': 'Tax Rate (%)', 'type': 'number'}
            ],
            'product-content': [{'name': 'content_name', 'label': 'Content Name', 'type': 'text'}],
            'drug-company': [
                {'name': 'company_name', 'label': 'Company Name', 'type': 'text'},
                {'name': 'sht_name', 'label': 'Short Name', 'type': 'text'}
            ],
            'drug-supplier': [
                {'name': 'name', 'label': 'Supplier Name', 'type': 'text'},
                {'name': 'phone', 'label': 'Phone', 'type': 'text'},
                {'name': 'address', 'label': 'Address', 'type': 'text'},
                {'name': 'gst_number', 'label': 'GST Number', 'type': 'text'},
                {'name': 'dl_number', 'label': 'DL Number', 'type': 'text'}
            ],
            'pharmacy-link': [
                {'name': 'pharmacy_name', 'label': 'Pharmacy Name', 'type': 'text', 'readonly': True},
                {'name': 'phone', 'label': 'Phone Number', 'type': 'text'},
                {'name': 'license_number', 'label': 'License Number (DL)', 'type': 'text'},
                {'name': 'gst_number', 'label': 'GST Number', 'type': 'text'},
                {'name': 'address', 'label': 'Address', 'type': 'text'}
            ],
        }
        return {
            'title': titles.get(master_type, 'Master'),
            'fields': fields.get(master_type, []),
            'master_type': master_type,
            'hide_add_button': master_type == 'pharmacy-link'
        }

    def get(self, request, master_type):
        model = self.get_model(master_type)
        if not model:
            return redirect('home')
        
        if master_type == 'pharmacy-link':
            items = model.objects.filter(id=request.tenant.id)
        else:
            items = model.objects.filter(tenant=request.tenant).order_by('id')
            
        paginator = Paginator(items, 25) # 25 items per page
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
            
        context = self.get_context_data(master_type)
        context['items'] = page_obj
        context['page_obj'] = page_obj
        return render(request, 'masters/generic_master.html', context)

    def post(self, request, master_type):
        model = self.get_model(master_type)
        if not model:
            return JsonResponse({'error': 'Invalid master type'}, status=400)
        
        post_data_lower = {k.lower(): request.POST.get(k) for k in request.POST.keys()}
        data = {field['name']: post_data_lower.get(field['name'].lower()) for field in self.get_context_data(master_type)['fields']}
        try:
            instance = model.objects.create(tenant=request.tenant, **data)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                first_field = self.get_context_data(master_type)['fields'][0]['name']
                return JsonResponse({'success': True, 'id': instance.id, 'name': getattr(instance, first_field)})
            messages.success(request, f"{master_type.replace('-', ' ').title()} added successfully.")
        except Exception as e:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'success': False, 'error': str(e)})
            messages.error(request, f"Error: {str(e)}")
            
        return redirect('master-crud', master_type=master_type)

    def patch(self, request, master_type):
        try:
            data = json.loads(request.body)
            model = self.get_model(master_type)
            if master_type == 'pharmacy-link':
                item = request.tenant
                if item.id != data.get('id'):
                    return JsonResponse({'error': 'Invalid tenant id'}, status=400)
            else:
                item = get_object_or_404(model, id=data.get('id'), tenant=request.tenant)
            
            for field in self.get_context_data(master_type)['fields']:
                if field['name'] in data:
                    setattr(item, field['name'], data[field['name']])
            
            item.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

    def delete(self, request, master_type):
        try:
            data = json.loads(request.body)
            model = self.get_model(master_type)
            if master_type == 'pharmacy-link':
                item = request.tenant
                if item.id != data.get('id'):
                    return JsonResponse({'error': 'Invalid tenant id'}, status=400)
            else:
                item = get_object_or_404(model, id=data.get('id'), tenant=request.tenant)
            item.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


# Keep Product views as they are more complex (file uploads, select2, etc.)
class ProductCreate(LoginRequiredMixin,View):
    template_name = 'masters/products/product.html'
    def get(self, request, product_id=None):
        product = None
        if product_id:
            product = get_object_or_404(Products, id=product_id, tenant=request.tenant)
            
        from django.db.models import Q
        context = {
            'product': product,
            'product_types': ProductType.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('name'),
            'product_schedules': ProductSchedule.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('schedule_name'),
            'product_taxes': ProductTax.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('tax_rate'),
            'product_contents': ProductContent.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('content_name'),
            'drug_companies': DrugCompany.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('company_name'),
        }
        return render(request, self.template_name, context)
    
    def post(self, request, product_id=None):
        try:
            if product_id:
                product = get_object_or_404(Products, id=product_id, tenant=request.tenant)
            else:
                product = Products(tenant=request.tenant)

            product.product_name = request.POST.get("product_name")
            product.product_packing = request.POST.get("product_packing")
            product.product_type_id = request.POST.get("product_type") or None
            product.product_schedule_id = request.POST.get("product_schedule") or None
            product.product_tax_id = request.POST.get("product_tax") or None
            product.product_hsn_code = request.POST.get("product_hsn_code")
            product.product_content_id = request.POST.get("product_content") or None
            product.compny_name_id = request.POST.get("compny_name") or None
            product.minimum_stock_level = request.POST.get('minimum_stock_level') or None
            
            # Ensure conversion factor is at least 1 and handled correctly if empty
            try:
                conv_val = request.POST.get("conversion_factor")
                product.conversion_factor = int(conv_val) if conv_val and int(conv_val) > 0 else 1
            except (ValueError, TypeError):
                product.conversion_factor = 1
                
            product.save()
            
            messages.success(request, f"Product {'updated' if product_id else 'added'} successfully.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        return redirect('all-products')

class QuickProductAPI(LoginRequiredMixin,View):
    # Your purchase entry view (wherever it renders entry.html)
    def get(self, request):
        from django.db.models import Q
        context = {
            'suppliers': Supplier.objects.filter(tenant=request.tenant),
            'product_taxes': ProductTax.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)),
            
            # ADD THESE TWO ↓
            'product_schedules': ProductSchedule.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('schedule_name'),
            'drug_companies': DrugCompany.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('company_name'),
            
            'today': date.today(),
        }
        
        return render(request, 'purchase/entry.html', context)
        
    def post(self, request):
        try:
            data = json.loads(request.body)
            product = Products.objects.create(
                tenant=request.tenant,
                product_name=data.get('name'),
                product_packing=data.get('packing'),
                product_tax_id=data.get('tax_id') or None,
                product_schedule_id=data.get('schedule_id') or None,
                compny_name_id=data.get('company_id') or None,
                product_hsn_code=data.get('hsn_code') or '',
                conversion_factor=int(data.get('conversion_factor', 1))
            )
            return JsonResponse({'success': True, 'id': product.id, 'name': product.product_name})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
    
    def patch(self, request, pk=None):
        try:
            data = json.loads(request.body)
    
            # pk comes from URL: /api/products/quick-add/<pk>/
            product_id = pk or data.get('id')
            product = get_object_or_404(Products, id=product_id, tenant=request.tenant)
    
            product.product_packing     = data.get('packing', product.product_packing)
            product.product_hsn_code    = data.get('hsn_code', product.product_hsn_code)
            product.product_tax_id      = data.get('tax_id') or None
            product.product_schedule_id = data.get('schedule_id') or None
            product.compny_name_id      = data.get('company_id') or None
    
            try:
                conv = data.get('conversion_factor')
                product.conversion_factor = int(conv) if conv and int(conv) > 0 else 1
            except (ValueError, TypeError):
                pass
    
            product.save()
    
            new_tax_rate = None
            if product.product_tax:
                new_tax_rate = float(product.product_tax.tax_rate)
    
            return JsonResponse({'success': True, 'tax_rate': new_tax_rate})
    
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

class ProductMasterSearchAPI(LoginRequiredMixin,View):
    def get(self, request):
        query = request.GET.get('q', '')
        limit_str = request.GET.get('limit', '20')
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 20
        products = Products.objects.filter(
            tenant=request.tenant,
            product_name__istartswith=query
        ).select_related('product_tax').only(
            'id', 'product_name', 'product_packing', 'conversion_factor', 'product_tax__tax_rate'
        )[:limit]
        
        data = []
        for p in products:
            data.append({
                'id': p.id,
                'name': p.product_name,
                'packing': p.product_packing or '',
                'conversion_factor': p.conversion_factor,
                'tax_rate': p.product_tax.tax_rate if p.product_tax else 0
            })
        return JsonResponse(data, safe=False)

class ProductListView(LoginRequiredMixin,View):
    template_name = 'masters/products/product_list.html'
    def get(self, request):
        query = request.GET.get('q', '')

        products = Products.objects.filter(tenant=request.tenant)
        if query:
            products = products.filter(
                Q(product_name__icontains=query) |
                Q(product_hsn_code__icontains=query)
            )
        
        products = products.select_related(
            'product_type',
            'product_schedule',
            'product_tax',
            'product_content',
            'compny_name'
        ).order_by('-id')
        paginator = Paginator(products, 20)
        page = request.GET.get('page')
        page_obj = paginator.get_page(page)

        context = {
            'products': page_obj,
            'page_obj': page_obj,
            'product_types': ProductType.objects.filter(tenant=request.tenant),
            'product_schedules': ProductSchedule.objects.filter(tenant=request.tenant),
            'search_query': query
        }

        return render(request, self.template_name, context)

    def delete(self, request):
        try:
            data = json.loads(request.body)
            product = get_object_or_404(Products, id=data.get('id'), tenant=request.tenant)
            product.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})