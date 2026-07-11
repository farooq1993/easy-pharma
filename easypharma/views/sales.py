from decimal import Decimal
from django.views import View
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import F, Q
from django.core.cache import cache
from easypharma.models.stock import StockBatch
from easypharma.models.Items import Products
from easypharma.models.print_setup import PrintSetup
from easypharma.models.sales import (SaleInvoice, SaleItem,
                                    Customer, SalesReturn, SalesReturnItem,PrescriptionReminder)
import json
from datetime import datetime
from urllib.parse import quote_plus

from easypharma.models.Items import Products, ProductTax
from easypharma.models.doctor import DoctorModel

# ── POS cache helpers ──────────────────────────────────────────
POS_CACHE_TIMEOUT = 180  # 3 minutes

def _pos_search_version(tenant_id):
    """Return current search-cache version for this tenant (create if absent)."""
    version_key = f'pos_search_v:{tenant_id}'
    version = cache.get(version_key)
    if version is None:
        cache.set(version_key, 1, timeout=None)  # never expires on its own
        version = 1
    return version

def _pos_products_cache_key(tenant_id):
    return f'pos_products:{tenant_id}'

def _pos_customers_cache_key(tenant_id):
    return f'pos_customers:{tenant_id}'


def invalidate_pos_cache(tenant_id):
    """Call after any stock-changing event (sale saved, deleted, purchase entry)."""
    cache.delete(_pos_products_cache_key(tenant_id))
    cache.delete(_pos_customers_cache_key(tenant_id))
    cache.delete(f'pos_next_inv:{tenant_id}')
    # Bust ALL per-query search cache entries at once via version bump
    try:
        cache.incr(_search_version_key(tenant_id))
    except ValueError:
        cache.set(_search_version_key(tenant_id), 1, timeout=None)

class POSView(LoginRequiredMixin,View):
    template_name = 'sales/pos.html'

    def get(self, request, invoice_id=None):
        tenant_id = request.tenant.id

        # ── product_taxes: tiny table, cache it ──
        product_taxes = cache.get(f'pos_taxes:{tenant_id}')
        if product_taxes is None:
            product_taxes = list(ProductTax.objects.filter(tenant=request.tenant))
            cache.set(f'pos_taxes:{tenant_id}', product_taxes, 600)  # 10 min

        # ── default_doctor: rarely changes, cache it ──
        default_doctor = cache.get(f'pos_default_doctor:{tenant_id}')
        if default_doctor is None:
            default_doctor = DoctorModel.objects.filter(
                tenant=request.tenant, is_default=True
            ).only('name').first()
            cache.set(f'pos_default_doctor:{tenant_id}', default_doctor, 600)
        # All doctor tenant wise
        doctors = DoctorModel.objects.filter(tenant=request.tenant).order_by('name')
        
        # ── next invoice number: cache with short TTL ──
        next_inv_key = f'pos_next_inv:{tenant_id}'
        next_invoice_number = cache.get(next_inv_key)
        if next_invoice_number is None:
            count = SaleInvoice.objects.filter(tenant=request.tenant).count()
            next_invoice_number = f"INV-{tenant_id}-{count + 1}"
            cache.set(next_inv_key, next_invoice_number, 30)  # 30s — refreshes often

        # ── NOTE: products & customers removed from context ──
        # Template never looped over them; search is done via /api/products/search/
        # Removing them saves serialising 100s of ORM objects on every page load.

        edit_invoice = None
        edit_data = None
        if invoice_id:
            try:
                edit_invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                items = []
                for item in edit_invoice.items.all().select_related('product'):
                    from easypharma.models.stock import StockBatch
                    batch = StockBatch.objects.filter(
                        tenant=request.tenant,
                        product=item.product,
                        batch_number=item.batch_number
                    ).first()
                    items.append({
                        'product_id': item.product.id,
                        'batch_id': batch.id if batch else None,
                        'product_name': item.product.product_name,
                        'batch_number': item.batch_number,
                        'expiry_date': item.expiry_date.strftime('%Y-%m-%d') if item.expiry_date else '',
                        'quantity': item.quantity,
                        'price': float(item.unit_price),
                        'tax_rate': float(item.tax_percentage),
                        'total': float(item.total_amount),
                        'discount_percentage': float(item.discount_percentage or 0)
                    })

                gross_amount = float(edit_invoice.sub_total or 0) + float(edit_invoice.tax_amount or 0)
                discount_amount = float(edit_invoice.discount_amount or 0)
                discount_percentage = gross_amount > 0 and (discount_amount / gross_amount) * 100 or 0

                edit_data = {
                    'invoice_id': edit_invoice.id,
                    'invoice_number': edit_invoice.invoice_number,
                    'patient_name': edit_invoice.patient_name,
                    'patient_phone': edit_invoice.patient_phone,
                    'doctor_name': edit_invoice.doctor_name,
                    'payment_mode': edit_invoice.payment_mode,
                    'discount_amount': discount_amount,
                    'discount_percentage': discount_percentage,
                    'items': items
                }
            except SaleInvoice.DoesNotExist:
                edit_data = None

        from easypharma.models import PrintSetup
        ps, _ = PrintSetup.objects.get_or_create(tenant=request.tenant)

        return render(request, self.template_name, {
            'product_taxes': product_taxes,
            'doctors':doctors,
            'default_doctor': default_doctor,
            'edit_data': edit_data,
            'next_invoice_number': next_invoice_number,
            'ps': ps,
        })

    def post(self, request):
        try:
            if not request.tenant:
                return JsonResponse({'success': False, 'error': 'No Pharmacy detected! Please assign a Pharmacy (Tenant) to your user account in Admin.'})
            
            data = json.loads(request.body)
            tenant_id = request.tenant.id
            from easypharma.models.stock import StockBatch
            
            with transaction.atomic():
                # Generate a unique invoice number
                count = SaleInvoice.objects.filter(tenant=request.tenant).count()
                invoice_no = f"INV-{tenant_id}-{count + 1}"
                
                invoice_id = data.get('invoice_id')
                if invoice_id:
                    invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                    # revert stock from previous items before editing
                    for old_item in invoice.items.all():
                        from easypharma.models.stock import StockBatch
                        batch = StockBatch.objects.filter(
                            tenant=request.tenant,
                            product=old_item.product,
                            batch_number=old_item.batch_number
                        ).first()
                        if batch:
                            batch.current_quantity += old_item.quantity
                            batch.save()
                    invoice.items.all().delete()
                    from easypharma.models.accounting import CustomerLedger
                    CustomerLedger.objects.filter(tenant=request.tenant, reference_number=invoice.invoice_number).delete()
                else:
                    invoice = SaleInvoice(
                        tenant=request.tenant,
                        user=request.user,
                        invoice_number=invoice_no
                    )
                

                invoice.patient_name = data.get('patient_name')
                invoice.patient_address = data.get('patient_address')
                invoice.patient_phone = data.get('patient_phone')
                invoice.doctor_name = data.get('doctor_name')
                invoice.sub_total = data['sub_total']
                invoice.tax_amount = data['tax_amount']
                invoice.discount_amount = data['discount_amount']
                invoice.total_amount = data['total_amount']
                invoice.payment_mode = data['payment_mode']
                invoice.sale_type = data.get('sale_type', 'Prescription')
                if invoice.payment_mode != 'Credit':
                    invoice.paid_amount = data['total_amount']
                else:
                    invoice.paid_amount = 0.00
                if data.get('invoice_number'):
                    invoice.invoice_number = data['invoice_number']
                invoice.save()

                # If payment mode is Credit, link/create customer account and post to CustomerLedger
                if invoice.payment_mode == 'Credit' and invoice.patient_name:
                    from easypharma.models.sales import Customer
                    customer, created = Customer.objects.get_or_create(
                        tenant=request.tenant,
                        name=invoice.patient_name.strip(),
                        defaults={
                            'phone': invoice.patient_phone or '',
                            'address': invoice.patient_address or '',
                        }
                    )
                    if not created and invoice.patient_phone and not customer.phone:
                        customer.phone = invoice.patient_phone
                        customer.save()
                    
                    invoice.customer = customer
                    invoice.save(update_fields=['customer'])
                    
                    from easypharma.models.accounting import CustomerLedger
                    CustomerLedger.objects.create(
                        tenant=request.tenant,
                        customer=customer,
                        date=invoice.created_at.date() if invoice.created_at else now().date(),
                        transaction_type='Sale',
                        reference_number=invoice.invoice_number,
                        debit=invoice.total_amount,
                        credit=0.00,
                        remarks=f"Sale Invoice #{invoice.invoice_number}"
                    )
                
                # Create Sale Items & Deduct Stock
                for item in data.get('items', []):
                    product = Products.objects.get(id=item['product_id'], tenant=request.tenant)
                    
                    # Deduct from SPECIFIC batch selected in POS
                    batch_id = item.get('batch_id')
                    if batch_id:
                        batch = StockBatch.objects.get(id=batch_id, tenant=request.tenant)
                    else:
                        # Fallback to FIFO if no batch_id (should not happen with new UI)
                        batch = StockBatch.objects.filter(
                            tenant=request.tenant, 
                            product=product,
                            current_quantity__gt=0
                        ).order_by('expiry_date').first()
                    
                    if not batch:
                        raise Exception(f"No stock available for {product.product_name}")
                    
                    # Calculate tax from product master
                    tax_rate = product.product_tax.tax_rate if product.product_tax else 0
                    quantity = item['quantity']
                    
                    # Calculate base price (since MRP is tax-inclusive)
                    unit_price = item['price']
                    base_price = unit_price / (1 + tax_rate / 100) if tax_rate > 0 else unit_price
                    tax_per_unit = unit_price - base_price
                    tax_amount = tax_per_unit * quantity
                    
                    SaleItem.objects.create(
                        tenant=request.tenant,
                        sale_invoice=invoice,
                        product=product,
                        batch_number=batch.batch_number,
                        expiry_date=batch.expiry_date,
                        quantity=quantity,
                        unit_price=unit_price,
                        tax_percentage=tax_rate,
                        tax_amount=tax_amount,
                        total_amount=item['total']
                    )
                    
                    # Update stock batch
                    batch.current_quantity -= quantity
                    if batch.current_quantity < 0:
                        raise Exception(f"Insufficient stock for {product.product_name}")
                    batch.save()
                
                # Calculate next invoice number
                count = SaleInvoice.objects.filter(tenant=request.tenant).count()
                next_inv = f"INV-{tenant_id}-{count + 1}"

                # ── Invalidate caches after successful sale ──
                try:
                    invalidate_pos_cache(tenant_id)
                    from easypharma.views.reports import invalidate_daily_sale_cache, invalidate_stock_cache
                    invalidate_daily_sale_cache(tenant_id)
                    invalidate_stock_cache(tenant_id)
                except Exception:
                    pass  # Cache invalidation failure should never break the sale flow

                return JsonResponse({
                    'success': True, 
                    'invoice_id': invoice.id, 
                    'invoice_number': invoice.invoice_number,
                    'next_invoice_number': next_inv
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

class PrintInvoiceView(LoginRequiredMixin, View):

    def get(self, request, invoice_id):
        invoice = get_object_or_404(
            SaleInvoice.objects.prefetch_related('items', 'items__product'),
            id=invoice_id
        )

        if not invoice.tenant and request.tenant:
            invoice.tenant = request.tenant
        tenant = invoice.tenant or request.tenant

        ps, _ = PrintSetup.objects.get_or_create(tenant=tenant)
        total_qty = sum(item.quantity for item in invoice.items.all())
        # Paper size ke hisab se template aur width select karo
        if ps.paper_size == 'A4':
            W = 55
            template = 'sales/print_invoice_a4.html'
            bill_text = self.generate_bill_text(invoice, ps, W)
            

        elif ps.paper_size in ['4x6', '8x4']:
            W = 65
            template = 'sales/print_invoice.html'
            single = self.generate_bill_text(invoice, ps, W)
            bill_text = single + "\n" + single  # 2 copies ek ke baad ek

        elif ps.paper_size in ['80mm', '58mm']:
            W = 32 if ps.paper_size == '58mm' else 42
            template = 'sales/print_invoice_thermal.html'
            bill_text = self.generate_bill_text(invoice, ps, W)

        else:
            W = 55
            template = 'sales/print_invoice_a4.html'
            bill_text = self.generate_bill_text(invoice, ps, W)

        return render(request, template, {
            'invoice': invoice,
            'ps': ps,
            'bill_text': bill_text,
            'copies': ['ORIGINAL', 'DUPLICATE'],  
            'total_qty': total_qty,
        })

    def generate_bill_text(self, invoice, ps, W):
        lines = []
        lines.append(" ")
        invoice_date = invoice.created_at.strftime('%d/%m/%Y')
        # === HEADER ===
        lines.append(" " + invoice.tenant.pharmacy_name.upper()[:W])
        if invoice.tenant.address:
            lines.append(" " + invoice.tenant.address.upper()[:W])

        # DL number
        if ps.show_dl_details and invoice.tenant.license_number:
            lines.append(" " + f"DL: {invoice.tenant.license_number}  Ph: {invoice.tenant.phone or ''}"[:W])
            lines.append(" " + f"Food License: {invoice.tenant.food_lic or ''}"[:W])
        # GST number
        if ps.show_gst_details and hasattr(invoice.tenant, 'gst_number') and invoice.tenant.gst_number:
            lines.append(" " + f"GST: {invoice.tenant.gst_number}"[:W])

        # Custom header
        if ps.custom_header:
            for ch_line in ps.custom_header.splitlines():
                lines.append(" " + ch_line[:W])

        lines.append(" " + f"{'CASH MEMO: ' + invoice.invoice_number + '  Dt: ' + invoice_date:>{W}}")
        lines.append(" " + "-" * W)

        # === PATIENT ===
        lines.append(" " + f"Pt  : {invoice.patient_name or 'CASH CUSTOMER'}"[:W])
        if invoice.patient_address:
            lines.append(" " + f"Addr: {invoice.patient_address}"[:W])
        lines.append(" " + f"Dr  : {invoice.doctor_name or 'SELF'}"[:W])
        lines.append(" " + "-" * W)

        # === ITEMS HEADER ===
        # W=65: product(28) + mfg(6) + batch(9) + exp(6) + qty(4) + value(10) = 63 + 2 space = 65
        # W=55: product(22) + mfg(5) + batch(8) + exp(6) + qty(4) + value(10) = 55
        if W >= 65:
            lines.append(" " +
                f"{'PRODUCT':<28}"
                f"{'MFG':<6}"
                f"{'BATCH':<9}"
                f"{'EXP':<6}"
                f"{'QT':>4}"
                f"{'VALUE':>10}"
            )
        else:
            lines.append(" " +
                f"{'PRODUCT':<22}"
                f"{'MFG':<5}"
                f"{'BATCH':<8}"
                f"{'EXP':<6}"
                f"{'QT':>4}"
                f"{'VALUE':>10}"
            )
        lines.append(" " + "-" * W)

        # === ITEMS ===
        total_qty = 0
        for item in invoice.items.all():
            total_qty += item.quantity

            if W >= 65:
                product_name = (item.product.product_name or "")[:27].upper()
            else:
                product_name = (item.product.product_name or "")[:21].upper()

            company_abbr = ""
            if item.product.compny_name and item.product.compny_name.sht_name:
                company_abbr = item.product.compny_name.sht_name[:6].upper()
            elif item.product.company:
                company_abbr = item.product.company.name[:6].upper()

            batch = (item.batch_number or "")[:9]
            exp = item.expiry_date.strftime("%m/%y") if item.expiry_date else ""

            if W >= 65:
                lines.append(" " +
                    f"{product_name:<28}"
                    f"{company_abbr:<6}"
                    f"{batch:<9}"
                    f"{exp:<6}"
                    f"{item.quantity:>4}"
                    f"{float(item.total_amount):>10.2f}"
                )
            else:
                lines.append(" " +
                    f"{product_name:<22}"
                    f"{company_abbr:<5}"
                    f"{batch:<8}"
                    f"{exp:<6}"
                    f"{item.quantity:>4}"
                    f"{float(item.total_amount):>10.2f}"
                )

        lines.append(" " + "-" * W)

        # === FOOTER ===
        lines.append(" " + f"Items: {invoice.items.count()}  Qty: {total_qty}")
        lines.append(" " + "-" * W)

        # Amounts
        lines.append(" " + f"{'Sub Total :':<20}{invoice.sub_total:>10.2f}")
        lines.append(" " + f"{'GST Amount:':<20}{invoice.tax_amount:>10.2f}")

        if invoice.discount_amount and invoice.discount_amount > 0:
            lines.append(" " + f"{'Discount  :':<20}{invoice.discount_amount:>10.2f}")

        round_off = invoice.total_amount - (
            invoice.sub_total + invoice.tax_amount - invoice.discount_amount
        )
        if abs(round_off) >= 0.01:
            lines.append(" " + f"{'Round Off :':<20}{round_off:>+10.2f}")

        lines.append(" " + f"{'NET AMOUNT:':<20}{invoice.total_amount:>10.2f}")
        lines.append(" " + "-" * W)

        # Signature (dot matrix me text se)
        if ps.show_pharmacist_signature:
            lines.append("")
            lines.append(" " + " " * 35 + "Pharmacist Signature")
            # lines.append(" " + " " * 35 + "____________________")

        # Custom footer
        if ps.custom_footer:
            lines.append("")
            for cf_line in ps.custom_footer.splitlines():
                lines.append(" " + cf_line[:W])

        # Jurisdiction
        city = getattr(invoice.tenant, 'city', None)
        if city:
            lines.append("")
            lines.append(f" Subject to Jurisdiction of {city}"[:W])

        lines.append(" " + "-" * W)

        return "\n".join(lines)

# class PrintInvoiceView(LoginRequiredMixin,View):
#     template_name = 'sales/print_invoice.html'

#     def get(self, request, invoice_id):
#         from django.shortcuts import get_object_or_404
#         from easypharma.models.print_setup import PrintSetup
#         invoice = get_object_or_404(SaleInvoice, id=invoice_id)
#         if not invoice.tenant and request.tenant:
#             invoice.tenant = request.tenant
#         # Load print settings (use tenant from invoice or request)
#         tenant = invoice.tenant or request.tenant
#         ps, _ = PrintSetup.objects.get_or_create(tenant=tenant)
#         return render(request, self.template_name, {'invoice': invoice, 'ps': ps})

class SaleListView(LoginRequiredMixin, View):
    template_name = 'sales/list.html'
    PAGE_SIZE = 20

    def get(self, request):
        qs = SaleInvoice.objects.filter(tenant=request.tenant).order_by('-created_at')

        # ── Filters ──────────────────────────────────────────────
        q = request.GET.get('q', '').strip()
        date_from = request.GET.get('date_from', '').strip()
        date_to   = request.GET.get('date_to', '').strip()
        payment   = request.GET.get('payment', '').strip()

        if q:
            qs = qs.filter(
                Q(patient_name__icontains=q) |
                Q(patient_phone__icontains=q) |
                Q(invoice_number__icontains=q) |
                Q(doctor_name__icontains=q)
            )
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
        if payment:
            qs = qs.filter(payment_mode=payment)

        # ── Totals for filtered set ───────────────────────────────
        from django.db.models import Sum as DbSum
        totals = qs.aggregate(
            total_revenue=DbSum('total_amount'),
            total_tax=DbSum('tax_amount')
        )

        # ── Pagination ───────────────────────────────────────────
        from django.core.paginator import Paginator
        paginator = Paginator(qs, self.PAGE_SIZE)
        page_num  = request.GET.get('page', 1)
        page_obj  = paginator.get_page(page_num)

        return render(request, self.template_name, {
            'invoices':  page_obj,
            'page_obj':  page_obj,
            'paginator': paginator,
            # preserve filters in pagination links
            'q':          q,
            'date_from':  date_from,
            'date_to':    date_to,
            'payment':    payment,
            'total_revenue': totals['total_revenue'] or 0,
            'total_tax':     totals['total_tax'] or 0,
        })

    def delete(self, request, invoice_id):
        try:
            with transaction.atomic():
                invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                
                # REVERT STOCK: Add back the sold quantities
                for item in invoice.items.all():
                    from easypharma.models.stock import StockBatch
                    batch = StockBatch.objects.filter(
                        tenant=request.tenant, 
                        product=item.product,
                        batch_number=item.batch_number
                    ).first()
                    
                    if batch:
                        batch.current_quantity += item.quantity
                        batch.save()
                
                invoice.delete()
                invalidate_pos_cache(request.tenant.id)
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})



class ProductSearchAPI(LoginRequiredMixin,View):

    CACHE_TIMEOUT = 120  # 2 minutes — short enough that new stock shows quickly

    @staticmethod
    def _cache_key(tenant_id, query):
        # Include version so invalidate_pos_cache() busts all search entries at once
        version = _pos_search_version(tenant_id)
        clean_query = query.lower().strip().replace(' ', '_')
        return f'pos_search:{tenant_id}:v{version}:{clean_query}'

    def get(self, request):
        query = request.GET.get('q', '').strip()
        limit_str = request.GET.get('limit', '10')
        try:
            limit = int(limit_str)
        except ValueError:
            limit = 10
        tenant_id = request.tenant.id
        
        # Include limit in cache key if preloading/limiting
        cache_key = f"{self._cache_key(tenant_id, query)}:lim{limit}"

        # ── Cache hit: return instantly without touching DB ──
        cached = cache.get(cache_key)
        if cached is not None:
            return JsonResponse(cached, safe=False)

        from easypharma.models.stock import StockBatch
        
        products = Products.objects.filter(
            tenant=request.tenant,
            product_name__istartswith=query
        ).select_related('product_tax', 'product_content', 'compny_name', 'product_schedule').prefetch_related('batches')[:limit]
        data = []
        for p in products:
            batches = p.batches.filter(current_quantity__gt=0).order_by('expiry_date')
            
            if not batches.exists():
                # Still return the product but flag as out of stock so UI can show substitute button
                data.append({
                    'id': p.id,
                    'name': p.product_name,
                    'packing': p.product_packing,
                    'content': p.product_content.content_name if p.product_content else None,
                    'company': p.compny_name.company_name if p.compny_name else None,
                    'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                    'conversion_factor': p.conversion_factor,
                    'out_of_stock': True,
                    'batches': []
                })
                continue
                
            batch_list = []
            for batch in batches:
                unit_price = float(batch.sale_price)
                if p.conversion_factor > 1:
                    unit_price = float(batch.mrp) / p.conversion_factor
                elif unit_price == 0 and batch.mrp:
                    unit_price = float(batch.mrp)
                
                batch_list.append({
                    'batch_id': batch.id,
                    'batch_no': batch.batch_number,
                    'expiry': batch.expiry_date.strftime('%m/%y'),
                    'stock': batch.current_quantity,
                    'price': unit_price,
                    'mrp_pack': float(batch.mrp)
                })
            
            data.append({
                'id': p.id,
                'name': p.product_name,
                'packing': p.product_packing,
                'content': p.product_content.content_name if p.product_content else None,
                'schedule': p.product_schedule.schedule_name if p.product_schedule else None,
                'company': p.compny_name.company_name if p.compny_name else None,
                'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                'conversion_factor': p.conversion_factor,
                'out_of_stock': False,
                'batches': batch_list
            })

        # ── Store in cache for next identical/same-case query ──
        cache.set(cache_key, data, self.CACHE_TIMEOUT)
        return JsonResponse(data, safe=False)


class SubstituteSearchAPI(LoginRequiredMixin,View):
    """Returns in-stock drugs with the same content/composition as the given product."""
    def get(self, request):
        product_id = request.GET.get('product_id')
        if not product_id:
            return JsonResponse([], safe=False)
        
        from easypharma.models.stock import StockBatch
        try:
            source = Products.objects.select_related('product_content').get(
                id=product_id, tenant=request.tenant
            )
        except Products.DoesNotExist:
            return JsonResponse([], safe=False)
        
        if not source.product_content:
            return JsonResponse([], safe=False)
        
        # Find other products with same content that have stock
        subs = Products.objects.filter(
            tenant=request.tenant,
            product_content=source.product_content,
        ).exclude(id=source.id).select_related(
            'product_tax', 'product_content', 'compny_name'
        ).prefetch_related('batches')[:15]
        
        data = []
        for p in subs:
            batches = p.batches.filter(current_quantity__gt=0).order_by('expiry_date')
            if not batches.exists():
                continue
            batch_list = []
            for batch in batches:
                unit_price = float(batch.sale_price)
                if p.conversion_factor > 1:
                    unit_price = float(batch.mrp) / p.conversion_factor
                elif unit_price == 0 and batch.mrp:
                    unit_price = float(batch.mrp)
                batch_list.append({
                    'batch_id': batch.id,
                    'batch_no': batch.batch_number,
                    'expiry': batch.expiry_date.strftime('%m/%y'),
                    'stock': batch.current_quantity,
                    'price': unit_price,
                })
            data.append({
                'id': p.id,
                'name': p.product_name,
                'packing': p.product_packing,
                'company': p.compny_name.company_name if p.compny_name else '—',
                'content': source.product_content.content_name,
                'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                'conversion_factor': p.conversion_factor,
                'batches': batch_list,
            })
        
        return JsonResponse(data, safe=False)


class SalesReturnView(LoginRequiredMixin,View):
    template_name = 'sales/sales_return.html'

    def get(self, request):
        customers = Customer.objects.filter(tenant=request.tenant).order_by('name')
        customer_id = request.GET.get('customer_id')
        customer_name = request.GET.get('customer_name', '').strip()
        invoice_id = request.GET.get('invoice_id')
        return_id = request.GET.get('return_id')
        selected_return = None
        selected_return_items = []
        
        context = {
            'customers': customers,
            'selected_customer': None,
            'selected_customer_name': None,
            'invoices': [],
            'selected_invoice': None,
            'sale_items': [],
            'returns': SalesReturn.objects.filter(tenant=request.tenant).order_by('-return_at')[:10],
            'selected_return': None,
            'selected_return_items': [],
        }
        
        if customer_id:
            try:
                customer = Customer.objects.get(id=customer_id, tenant=request.tenant)
                context['selected_customer'] = customer
                context['selected_customer_name'] = customer.name
                context['invoices'] = SaleInvoice.objects.filter(
                    tenant=request.tenant
                ).filter(
                    Q(customer=customer) |
                    Q(patient_name__iexact=customer.name) |
                    Q(patient_phone__icontains=customer.phone)
                ).order_by('-created_at')
            except Customer.DoesNotExist:
                messages.error(request, 'Customer not found.')
        elif customer_name:
            context['selected_customer_name'] = customer_name
            context['invoices'] = SaleInvoice.objects.filter(
                tenant=request.tenant
            ).filter(
                Q(patient_name__iexact=customer_name) |
                Q(patient_name__icontains=customer_name) |
                Q(patient_phone__icontains=customer_name)
            ).order_by('-created_at')
            if not context['invoices']:
                messages.error(request, 'No invoices found for this customer name.')
        
        if invoice_id:
            try:
                invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                context['selected_invoice'] = invoice
                context['sale_items'] = invoice.items.all().select_related('product')
            except SaleInvoice.DoesNotExist:
                messages.error(request, 'Invoice not found.')

        if return_id:
            try:
                selected_return = SalesReturn.objects.get(id=return_id, tenant=request.tenant)
                context['selected_return'] = selected_return
                context['selected_invoice'] = selected_return.sale_invoice
                context['selected_return_items'] = selected_return.return_items.select_related('sale_item__product').all()
                if selected_return.sale_invoice.customer:
                    context['selected_customer'] = selected_return.sale_invoice.customer
                else:
                    context['selected_customer_name'] = selected_return.sale_invoice.patient_name or ''
            except SalesReturn.DoesNotExist:
                messages.error(request, 'Return record not found.')

        return render(request, self.template_name, context)

    def post(self, request):
        action = request.POST.get('action')
        
        if action == 'select_customer':
            customer_id = request.POST.get('customer_id')
            customer_name = request.POST.get('customer_name', '').strip()
            if customer_id:
                return redirect(f"{request.path}?customer_id={customer_id}")
            if customer_name:
                customer = Customer.objects.filter(
                    tenant=request.tenant
                ).filter(
                    Q(name__iexact=customer_name) |
                    Q(name__icontains=customer_name) |
                    Q(phone__icontains=customer_name)
                ).first()
                if customer:
                    return redirect(f"{request.path}?customer_id={customer.id}")
                return redirect(f"{request.path}?customer_name={quote_plus(customer_name)}")
            messages.error(request, 'Please select a valid customer from the list.')
            return redirect('pos_returns_no_slash')
        
        elif action == 'select_invoice':
            customer_id = request.POST.get('customer_id')
            customer_name = request.POST.get('customer_name', '').strip()
            invoice_id = request.POST.get('invoice_id')
            if invoice_id:
                if customer_id:
                    return redirect(f"{request.path}?customer_id={customer_id}&invoice_id={invoice_id}")
                if customer_name:
                    return redirect(f"{request.path}?customer_name={quote_plus(customer_name)}&invoice_id={invoice_id}")
                return redirect(f"{request.path}?invoice_id={invoice_id}")
            else:
                messages.error(request, 'Please select an invoice.')
                if customer_id:
                    return redirect(f"{request.path}?customer_id={customer_id}")
                if customer_name:
                    return redirect(f"{request.path}?customer_name={quote_plus(customer_name)}")
                return redirect('pos_returns')
        
        elif action == 'process_return':
            invoice_id = request.POST.get('invoice_id')
            return_items = request.POST.getlist('return_items[]')
            return_quantities = request.POST.getlist('return_quantities[]')
            return_reasons = request.POST.getlist('return_reasons[]')
            
            if not invoice_id:
                messages.error(request, 'Invoice not found.')
                return redirect('pos_returns')
            
            invoice = get_object_or_404(SaleInvoice, id=invoice_id, tenant=request.tenant)
            
            if not return_items:
                messages.error(request, 'Please select items to return.')
                return redirect(request.META.get('HTTP_REFERER', 'pos_returns'))
            
            try:
                with transaction.atomic():
                    return_record = SalesReturn.objects.create(
                        tenant=request.tenant,
                        sale_invoice=invoice,
                        return_qty=0,
                        return_amount=Decimal('0')
                    )
                    
                    total_returned_qty = 0
                    total_return_amount = Decimal('0')
                    
                    for i, item_id in enumerate(return_items):
                        sale_item = SaleItem.objects.get(id=item_id, sale_invoice=invoice)
                        qty_to_return = int(return_quantities[i])
                        reason = return_reasons[i] if i < len(return_reasons) else ''
                        
                        if qty_to_return > 0 and qty_to_return <= sale_item.quantity:
                            SalesReturnItem.objects.create(
                                tenant=request.tenant,
                                sales_return=return_record,
                                sale_item=sale_item,
                                returned_quantity=qty_to_return,
                                return_reason=reason
                            )
                            
                            StockBatch.objects.filter(
                                tenant=request.tenant,
                                product=sale_item.product,
                                batch_number=sale_item.batch_number
                            ).update(current_quantity=F('current_quantity') + qty_to_return)
                            
                            total_returned_qty += qty_to_return
                            total_return_amount += Decimal(str(qty_to_return)) * sale_item.unit_price
                    
                    return_record.return_qty = total_returned_qty
                    return_record.return_amount = total_return_amount
                    return_record.save()
                    
                    try:
                        from easypharma.views.reports import invalidate_daily_sale_cache
                        invalidate_daily_sale_cache(request.tenant.id, date_str=str(return_record.return_at.date()))
                    except Exception:
                        pass
                    
                    messages.success(request, f"Return created ({return_record.return_inv_no}). {total_returned_qty} items | ₹{total_return_amount} returned.")
            except Exception as e:
                import traceback
                traceback.print_exc()
                messages.error(request, f"Unable to process return: {e}")
            
            return redirect('pos_returns')

        elif action == 'update_return':
            return_id = request.POST.get('return_id')
            return_item_ids = request.POST.getlist('return_item_ids[]')
            return_quantities = request.POST.getlist('return_quantities[]')
            return_reasons = request.POST.getlist('return_reasons[]')

            if not return_id:
                messages.error(request, 'Return record not found.')
                return redirect('pos_returns')

            try:
                with transaction.atomic():
                    return_record = SalesReturn.objects.select_for_update().get(id=return_id, tenant=request.tenant)
                    total_returned_qty = 0
                    total_return_amount = Decimal('0')

                    for i, item_id in enumerate(return_item_ids):
                        item = SalesReturnItem.objects.select_for_update().get(id=item_id, sales_return=return_record)
                        new_qty = int(return_quantities[i])
                        reason = return_reasons[i] if i < len(return_reasons) else ''
                        delta_qty = new_qty - item.returned_quantity

                        if new_qty < 0 or new_qty > item.sale_item.quantity:
                            raise ValueError('Invalid return quantity.')

                        batch_qs = StockBatch.objects.filter(
                            tenant=request.tenant,
                            product=item.sale_item.product,
                            batch_number=item.sale_item.batch_number
                        )
                        batch_qs.update(current_quantity=F('current_quantity') + delta_qty)

                        if new_qty == 0:
                            item.delete()
                        else:
                            item.returned_quantity = new_qty
                            item.return_reason = reason
                            item.save()
                            total_returned_qty += new_qty
                            total_return_amount += Decimal(str(new_qty)) * item.sale_item.unit_price

                    if total_returned_qty == 0:
                        return_date = return_record.return_at.date()
                        return_record.delete()
                        messages.success(request, 'Return record deleted because there are no returned items.')
                    else:
                        return_record.return_qty = total_returned_qty
                        return_record.return_amount = total_return_amount
                        return_record.save()
                        messages.success(request, f"Return updated ({return_record.return_inv_no}). {total_returned_qty} items | ₹{total_return_amount} returned.")

                    try:
                        from easypharma.views.reports import invalidate_daily_sale_cache
                        invalidate_daily_sale_cache(request.tenant.id, date_str=str(return_record.return_at.date()))
                    except Exception:
                        pass
            except Exception as e:
                import traceback
                traceback.print_exc()
                messages.error(request, f"Unable to update return: {e}")

            return redirect(f"{request.path}?return_id={return_id}")

        elif action == 'delete_return':
            return_id = request.POST.get('return_id')
            if not return_id:
                messages.error(request, 'Return record not found.')
                return redirect('pos_returns')
            try:
                with transaction.atomic():
                    return_record = SalesReturn.objects.select_for_update().get(id=return_id, tenant=request.tenant)
                    return_date = return_record.return_at.date()
                    for item in return_record.return_items.select_related('sale_item'):
                        StockBatch.objects.filter(
                            tenant=request.tenant,
                            product=item.sale_item.product,
                            batch_number=item.sale_item.batch_number
                        ).update(current_quantity=F('current_quantity') - item.returned_quantity)
                    return_record.delete()
                    try:
                        from easypharma.views.reports import invalidate_daily_sale_cache
                        invalidate_daily_sale_cache(request.tenant.id, date_str=str(return_date))
                    except Exception:
                        pass
                    messages.success(request, 'Return record deleted successfully.')
            except Exception as e:
                import traceback
                traceback.print_exc()
                messages.error(request, f"Unable to delete return: {e}")

            return redirect('pos_returns')

        return redirect('pos_returns')


class PatientWiseSales(LoginRequiredMixin,View):
    template_name = "sales/patient_wise_sales.html"

    def get(self, request):
        return render(request, self.template_name)


class PatientWiseSalesAPI(LoginRequiredMixin,View):
    def get(self, request):
        patient_name = request.GET.get('patient_name', '').strip()
        if not patient_name:
            return JsonResponse({'error': 'Patient name is required'}, status=400)
        
        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            patient_name__icontains=patient_name
        ).order_by('-created_at')
        
        data = []
        for sale in sales:
            items = []
            for item in sale.items.all().select_related('product'):
                items.append({
                    'product_name': item.product.product_name,
                    'batch_number': item.batch_number,
                    'expiry_date': item.expiry_date.strftime('%Y-%m-%d') if item.expiry_date else '',
                    'quantity': item.quantity,
                    'unit_price': float(item.unit_price),
                    'total': float(item.total_amount)
                })
            data.append({
                'invoice_number': sale.invoice_number,
                'date': sale.created_at.strftime('%Y-%m-%d %H:%M'),
                'doctor_name': sale.doctor_name,
                'payment_mode': sale.payment_mode,
                'total_amount': float(sale.total_amount),
                'items': items
            })
        
        return JsonResponse(data, safe=False)


class PrescriptionReminderView(LoginRequiredMixin,View):
    template_name = "sales/prescription_reminders.html"

    def get(self, request):
        reminders = PrescriptionReminder.objects.filter(tenant=request.tenant).order_by('reminder_date')
        customers = SaleInvoice.objects.filter(tenant=request.tenant).exclude(patient_name__isnull=True).exclude(
                    patient_name='').values_list('patient_name',flat=True).distinct().order_by('patient_name')

        inv_items = SaleItem.objects.filter(sale_invoice__tenant=request.tenant).select_related('sale_invoice', 'product')
        reminders = PrescriptionReminder.objects.filter(tenant=request.tenant).order_by('reminder_date')

        
        return render(request, self.template_name, {
            'reminders': reminders,
            'customers': customers,
            'inv_items': inv_items,
            'today': timezone.now().date()   # for status badge
        })
    
    def post(self, request):
        patient_name = request.POST.get('customer_id')
        prescription_date = request.POST.get('prescription_date')
        reminder_date = request.POST.get('reminder_date')
        notes = request.POST.get('notes', '').strip()
        
        if not (patient_name and prescription_date and reminder_date):
            messages.error(request, 'Customer, prescription date, and reminder date are required.')
            return redirect('prescription_reminders')
        
        try:
            patient_name = request.POST.get('customer_id')
            reminder = PrescriptionReminder.objects.create(
                tenant=request.tenant,
                patient_name=patient_name,
                prescription_date=prescription_date,
                reminder_date=reminder_date,
                notes=notes
            )
            messages.success(request, f"Reminder set for {patient_name} on {reminder.reminder_date}.")
        except Customer.DoesNotExist:
            messages.error(request, 'Customer not found.')
        except Exception as e:
            messages.error(request, f"Error creating reminder: {e}")
        
        return redirect('prescription_reminders')
    
class PrescriptionReminderDeleteView(LoginRequiredMixin,View):

    def post(self, request, reminder_id):

        try:
            reminder = PrescriptionReminder.objects.get(
                id=reminder_id,
                tenant=request.tenant
            )

            reminder.delete()

            return JsonResponse({
                'success': True
            })

        except PrescriptionReminder.DoesNotExist:

            return JsonResponse({
                'success': False,
                'error': 'Reminder not found'
            })

# ==================== NEW AJAX VIEW ====================
def get_customer_invoices(request):

    patient_name = request.GET.get('patient_name')

    items = SaleItem.objects.filter(
        sale_invoice__tenant=request.tenant,
        sale_invoice__patient_name=patient_name
    ).select_related(
        'sale_invoice',
        'product'
    )

    data = []

    for item in items:
        data.append({
            'id': item.id,
            'product_name': item.product.product_name,
            'invoice_number': item.sale_invoice.invoice_number,
        })

    return JsonResponse({
        'products': data
    })