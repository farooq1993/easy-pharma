from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse, Http404
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
            
        search_query = request.GET.get('q', '').strip()
        if search_query:
            search_fields = self.get_context_data(master_type).get('fields', [])
            q_objects = Q()
            for field in search_fields:
                if field.get('type') == 'text':
                    q_objects |= Q(**{f"{field['name']}__icontains": search_query})
            if q_objects:
                items = items.filter(q_objects)

        paginator = Paginator(items, 25) # 25 items per page
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
            
        context = self.get_context_data(master_type)
        context['items'] = page_obj
        context['page_obj'] = page_obj
        context['search_query'] = search_query
        return render(request, 'masters/generic_master.html', context)

    def post(self, request, master_type):
        model = self.get_model(master_type)
        if not model:
            return JsonResponse({'error': 'Invalid master type'}, status=400)
        
        post_data_lower = {k.lower(): request.POST.get(k) for k in request.POST.keys()}
        data = {field['name']: post_data_lower.get(field['name'].lower()) for field in self.get_context_data(master_type)['fields']}

        if master_type == 'product-tax':
            raw_name = (data.get('tax_name') or '').strip()
            raw_rate = data.get('tax_rate')

            rate_val = None
            if raw_rate is not None and str(raw_rate).strip() != '':
                try:
                    clean_str = str(raw_rate).replace('%', '').strip()
                    rate_val = int(round(float(clean_str)))
                except (ValueError, TypeError):
                    rate_val = None

            # Fallback: extract rate from tax_name if tax_rate wasn't provided or invalid
            if rate_val is None and raw_name:
                import re
                match = re.search(r'(\d+(\.\d+)?)', raw_name)
                if match:
                    try:
                        rate_val = int(round(float(match.group(1))))
                    except (ValueError, TypeError):
                        rate_val = None

            if not raw_name and rate_val is not None:
                raw_name = f"GST {rate_val}%"
            elif raw_name and raw_name.isdigit() and rate_val is not None:
                raw_name = f"GST {rate_val}%"

            data['tax_name'] = raw_name
            data['tax_rate'] = rate_val

        try:
            instance = model.objects.create(tenant=request.tenant, **data)
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                first_field = self.get_context_data(master_type)['fields'][0]['name']
                display_name = getattr(instance, first_field)
                tax_rate_val = getattr(instance, 'tax_rate', None)
                if master_type == 'product-tax' and tax_rate_val is not None:
                    if '%' not in str(display_name):
                        display_name = f"{display_name} ({tax_rate_val}%)"
                return JsonResponse({
                    'success': True,
                    'id': instance.id,
                    'name': display_name,
                    'tax_rate': tax_rate_val
                })
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
            
            if master_type == 'product-tax':
                raw_name = (data.get('tax_name') or item.tax_name or '').strip()
                raw_rate = data.get('tax_rate')
                rate_val = None
                if raw_rate is not None and str(raw_rate).strip() != '':
                    try:
                        clean_str = str(raw_rate).replace('%', '').strip()
                        rate_val = int(round(float(clean_str)))
                    except (ValueError, TypeError):
                        rate_val = None

                if rate_val is None and raw_name:
                    import re
                    match = re.search(r'(\d+(\.\d+)?)', raw_name)
                    if match:
                        try:
                            rate_val = int(round(float(match.group(1))))
                        except (ValueError, TypeError):
                            rate_val = None

                if rate_val is not None:
                    data['tax_rate'] = rate_val

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
        except Http404:
            return JsonResponse({'success': True, 'message': 'Record already deleted'})
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

from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator

@method_decorator(ensure_csrf_cookie, name='dispatch')
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
    CACHE_TIMEOUT = 120  # 2 minutes

    def get(self, request):
        from django.core.cache import cache

        raw_query = request.GET.get('q', '')
        query = raw_query.strip()
        limit_str = request.GET.get('limit', '50')
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 50

        tenant_id = request.tenant.id
        cache_key = f'master_search:{tenant_id}:{query.lower()}:lim{limit}'
        
        nocache = request.GET.get('nocache') == '1'
        if not nocache:
            cached = cache.get(cache_key)
            if cached is not None:
                response = JsonResponse(cached, safe=False)
                response['Cache-Control'] = 'private, max-age=30, stale-while-revalidate=60'
                return response

        tenant_filter = Q(tenant=request.tenant) | Q(tenant__isnull=True)
        qs = Products.objects.filter(tenant_filter)

        if query:
            qs = qs.filter(
                Q(product_name__icontains=query) |
                Q(product_content__content_name__icontains=query) |
                Q(compny_name__company_name__icontains=query)
            )

        products = qs.select_related(
            'product_tax', 'product_schedule', 'product_content', 'compny_name'
        ).only(
            'id', 'product_name', 'product_packing', 'conversion_factor', 'product_tax__tax_rate',
            'product_schedule__schedule_name', 'compny_name__company_name', 'product_hsn_code',
            'product_content__content_name'
        ).order_by('product_name')[:limit]
        
        data = []
        for p in products:
            data.append({
                'id': p.id,
                'name': p.product_name,
                'packing': p.product_packing or '',
                'conversion_factor': p.conversion_factor or 1,
                'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                'schedule_id': p.product_schedule_id or '',
                'schedule_name': p.product_schedule.schedule_name if p.product_schedule else '',
                'company_id': p.compny_name_id or '',
                'company_name': p.compny_name.company_name if p.compny_name else '',
                'hsn_code': p.product_hsn_code or '',
                'salt': p.product_content.content_name if p.product_content else ''
            })
        cache.set(cache_key, data, self.CACHE_TIMEOUT)
        response = JsonResponse(data, safe=False)
        response['Cache-Control'] = 'private, max-age=30, stale-while-revalidate=60'
        return response

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


import os
import re
import requests
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

@method_decorator(csrf_exempt, name='dispatch')
class AIProductAutoFillAPI(LoginRequiredMixin, View):
    def post(self, request):
        if not request.tenant:
            return JsonResponse({'success': False, 'error': 'No Pharmacy detected!'})

        try:
            data = json.loads(request.body)
            product_name = (data.get('product_name') or '').strip()

            if not product_name:
                return JsonResponse({'success': False, 'error': 'Medicine name is required.'})

            from easypharma.utility.purchase_ocr_service import GEMINI_API_KEY
            api_key = GEMINI_API_KEY
            if api_key:
                api_key = api_key.split('#')[0].strip().split()[0]
            
            if not api_key:
                return JsonResponse({'success': False, 'error': 'AI Auto-Fill service is not configured. Please contact administrator.'})

            prompt = (
                f"You are an expert Indian pharmacy database AI.\n"
                f"Given the medicine name: '{product_name}', look up and return accurate specifications and master details used in Indian pharmacy inventory:\n\n"
                f"1. product_name: Full clean brand name with strength/dosage (e.g. 'Zerodol SP Tablet')\n"
                f"2. packing: Standard packaging string (e.g. '10 Tablets / Strip', '100ml Bottle', '1 Injection')\n"
                f"3. conversion_factor: Integer units per box/strip (e.g. 10 for a strip of 10 tablets, 1 for syrup/injection/creams)\n"
                f"4. product_type: Product category (e.g. 'Tablet', 'Capsule', 'Syrup', 'Injection', 'Ointment', 'Gel', 'Drops', 'Sachet')\n"
                f"5. tax_rate: Standard GST percentage as number (e.g. 5.0, 12.0, 18.0. Default to 12.0 for standard medicines, 5.0 for essentials)\n"
                f"6. schedule: Drug schedule classification (e.g. 'Schedule H', 'Schedule H1', 'Schedule C', 'Schedule X', 'OTC', 'General')\n"
                f"7. content: Active chemical composition / salt formula (e.g. 'Aceclofenac 100mg + Paracetamol 325mg + Serratiopeptidase 15mg')\n"
                f"8. company: Pharmaceutical manufacturer / brand company (e.g. 'Ipca Laboratories Ltd', 'Cipla Ltd', 'Sun Pharmaceutical', 'Mankind Pharma')\n"
                f"9. hsn_code: Standard 4 or 8 digit HSN code for medicines (e.g. '30049099' or '3004')\n\n"
                f"Output MUST be a valid JSON object matching this schema:\n"
                f"{{\n"
                f"  \"product_name\": \"string\",\n"
                f"  \"packing\": \"string\",\n"
                f"  \"conversion_factor\": integer,\n"
                f"  \"product_type\": \"string\",\n"
                f"  \"tax_rate\": float,\n"
                f"  \"schedule\": \"string\",\n"
                f"  \"content\": \"string\",\n"
                f"  \"company\": \"string\",\n"
                f"  \"hsn_code\": \"string\"\n"
                f"}}\n\n"
                f"Return ONLY the raw JSON block without markdown code fences."
            )

            models_to_try = [
                ("v1beta", "gemini-3.6-flash"),
                ("v1beta", "gemini-3.5-flash-lite"),
                ("v1beta", "gemini-flash-latest"),
                ("v1beta", "gemini-flash-lite-latest"),
                ("v1beta", "gemini-3.5-flash"),
                ("v1beta", "gemini-3.1-flash-lite"),
                ("v1beta", "gemini-2.5-flash"),
            ]

            headers = {'Content-Type': 'application/json'}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.1, "response_mime_type": "application/json"}
            }

            response = None
            last_error = None
            for api_version, model_name in models_to_try:
                url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model_name}:generateContent?key={api_key}"
                try:
                    res = requests.post(url, headers=headers, json=payload, timeout=15)
                    if res.status_code == 200:
                        response = res
                        break
                    else:
                        last_error = f"{model_name} status {res.status_code}"
                except Exception as e:
                    last_error = f"{model_name} exception: {str(e)}"

            if not response or response.status_code != 200:
                return JsonResponse({'success': False, 'error': 'AI Auto-Fill could not retrieve details for this product. Please enter details manually.'})

            resp_json = response.json()
            raw_text = resp_json['candidates'][0]['content']['parts'][0]['text'].strip()
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', raw_text, re.DOTALL)
            if match:
                raw_text = match.group(1)

            ai_data = json.loads(raw_text.strip())

            # ── 1. Match or Create ProductType ──
            type_name = (ai_data.get('product_type') or 'Tablet').strip()
            ptype = ProductType.objects.filter(
                Q(tenant=request.tenant) | Q(tenant__isnull=True),
                name__iexact=type_name
            ).first()
            if not ptype and type_name:
                ptype = ProductType.objects.create(tenant=request.tenant, name=type_name.capitalize())

            # ── 2. Match or Create ProductTax ──
            try:
                tax_rate_val = float(ai_data.get('tax_rate') or 12.0)
            except (ValueError, TypeError):
                tax_rate_val = 12.0
            ptax = ProductTax.objects.filter(
                Q(tenant=request.tenant) | Q(tenant__isnull=True),
                tax_rate=tax_rate_val
            ).first()
            if not ptax:
                ptax = ProductTax.objects.create(
                    tenant=request.tenant,
                    tax_name=f"GST {int(tax_rate_val) if tax_rate_val.is_integer() else tax_rate_val}%",
                    tax_rate=tax_rate_val
                )

            # ── 3. Match or Create ProductSchedule ──
            sched_name = (ai_data.get('schedule') or 'General').strip()
            psched = ProductSchedule.objects.filter(
                Q(tenant=request.tenant) | Q(tenant__isnull=True),
                schedule_name__iexact=sched_name
            ).first()
            if not psched and sched_name:
                psched = ProductSchedule.objects.create(tenant=request.tenant, schedule_name=sched_name)

            # ── 4. Match or Create ProductContent (Composition / Salt) ──
            content_name = (ai_data.get('content') or '').strip()
            pcontent = None
            if content_name:
                pcontent = ProductContent.objects.filter(
                    Q(tenant=request.tenant) | Q(tenant__isnull=True),
                    content_name__iexact=content_name
                ).first()
                if not pcontent:
                    pcontent = ProductContent.objects.create(tenant=request.tenant, content_name=content_name)

            # ── 5. Match or Create DrugCompany ──
            company_name = (ai_data.get('company') or '').strip()
            pcomp = None
            if company_name:
                pcomp = DrugCompany.objects.filter(
                    Q(tenant=request.tenant) | Q(tenant__isnull=True),
                    company_name__iexact=company_name
                ).first()
                if not pcomp:
                    pcomp = DrugCompany.objects.create(tenant=request.tenant, company_name=company_name)

            return JsonResponse({
                'success': True,
                'data': {
                    'product_name': ai_data.get('product_name') or product_name,
                    'packing': ai_data.get('packing') or '10 Tablets / Strip',
                    'conversion_factor': int(ai_data.get('conversion_factor') or 1),
                    'hsn_code': ai_data.get('hsn_code') or '30049099',
                    'type_id': ptype.id if ptype else None,
                    'type_name': ptype.name if ptype else '',
                    'tax_id': ptax.id if ptax else None,
                    'tax_name': f"{ptax.tax_name} ({ptax.tax_rate}%)" if ptax else '',
                    'schedule_id': psched.id if psched else None,
                    'schedule_name': psched.schedule_name if psched else '',
                    'content_id': pcontent.id if pcontent else None,
                    'content_name': pcontent.content_name if pcontent else '',
                    'company_id': pcomp.id if pcomp else None,
                    'company_name': pcomp.company_name if pcomp else '',
                }
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)