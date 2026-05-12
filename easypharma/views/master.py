from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
import json
from django.core.paginator import Paginator
from django.apps import apps

from easypharma.models.Items import (DrugCompany, ProductContent, 
                                     ProductSchedule,
                                     ProductTax, ProductType, Products)
from easypharma.models.purchase_invoice import Supplier

class MasterCRUDView(View):
    """
    Generic view to handle CRUD for all master models.
    """
    http_method_names = ['get', 'post', 'patch', 'delete']
    
    def get_model(self, master_type):
        models_map = {
            'product-type': ProductType,
            'drug-schedule': ProductSchedule,
            'product-tax': ProductTax,
            'product-content': ProductContent,
            'drug-company': DrugCompany,
            'drug-supplier': Supplier,
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
                {'name': 'gst_number', 'label': 'GST Number', 'type': 'text'},
                {'name': 'dl_number', 'label': 'DL Number', 'type': 'text'}
            ],
        }
        return {
            'title': titles.get(master_type, 'Master'),
            'fields': fields.get(master_type, []),
            'master_type': master_type
        }

    def get(self, request, master_type):
        model = self.get_model(master_type)
        if not model:
            return redirect('home')
        
        items = model.objects.filter(tenant=request.tenant).order_by('id')
        context = self.get_context_data(master_type)
        context['items'] = items
        return render(request, 'masters/generic_master.html', context)

    def post(self, request, master_type):
        model = self.get_model(master_type)
        if not model:
            return JsonResponse({'error': 'Invalid master type'}, status=400)
        
        data = {field['name']: request.POST.get(field['name']) for field in self.get_context_data(master_type)['fields']}
        try:
            model.objects.create(tenant=request.tenant, **data)
            messages.success(request, f"{master_type.replace('-', ' ').title()} added successfully.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
            
        return redirect('master-crud', master_type=master_type)

    def patch(self, request, master_type):
        try:
            data = json.loads(request.body)
            model = self.get_model(master_type)
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
            item = get_object_or_404(model, id=data.get('id'), tenant=request.tenant)
            item.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)


# Keep Product views as they are more complex (file uploads, select2, etc.)
class ProductCreate(View):
    template_name = 'masters/products/product.html'
    def get(self, request):
        context = {
            'product_types': ProductType.objects.filter(tenant=request.tenant),
            'product_schedules': ProductSchedule.objects.filter(tenant=request.tenant),
            'product_taxes': ProductTax.objects.filter(tenant=request.tenant),
            'product_contents': ProductContent.objects.filter(tenant=request.tenant),
            'drug_companies': DrugCompany.objects.filter(tenant=request.tenant),
        }
        return render(request, self.template_name, context)
    
    def post(self, request):
        try:
            Products.objects.create(
                tenant=request.tenant,
                product_name=request.POST.get("product_name"),
                product_packing=request.POST.get("product_packing"),
                product_type_id=request.POST.get("product_type") or None,
                product_schedule_id=request.POST.get("product_schedule") or None,
                product_tax_id=request.POST.get("product_tax") or None,
                product_hsn_code=request.POST.get("product_hsn_code"),
                product_content_id=request.POST.get("product_content") or None,
                compny_name_id = request.POST.get("compny_name") or None
            )
            messages.success(request, "Product added successfully.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        return redirect('all-products')

class QuickProductAPI(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            product = Products.objects.create(
                tenant=request.tenant,
                product_name=data.get('name'),
                product_packing=data.get('packing'),
                product_tax_id=data.get('tax_id'),
                conversion_factor=int(data.get('conversion_factor', 1))
            )
            return JsonResponse({'success': True, 'id': product.id, 'name': product.product_name})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

class ProductListView(View):
    template_name = 'masters/products/product_list.html'
    def get(self, request):
        products = Products.objects.filter(tenant=request.tenant).select_related(
            'product_type', 'product_schedule', 'product_tax', 'product_content', 'compny_name'
        )
        paginator = Paginator(products, 10)
        page = request.GET.get('page')
        return render(request, self.template_name, {'products': paginator.get_page(page)})