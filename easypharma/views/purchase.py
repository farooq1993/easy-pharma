from django.views import View
from django.shortcuts import render, redirect
from django.http import JsonResponse,HttpResponse
from django.core.paginator import Paginator
from django.core.cache import cache
from django.db.models import Sum,F, Q, Min
from django.contrib.auth.mixins import LoginRequiredMixin
import csv
from easypharma.views.reports import render_to_pdf
from easypharma.models.Items import (Products,DrugCompany, ProductContent, 
                                     ProductSchedule,
                                     ProductTax, ProductType)

from easypharma.models.purchase_invoice import Supplier, PurchaseInvoice, PurchaseItem,OpeningStock,OpeningStockItem
from easypharma.models.stock import StockBatch
from easypharma.models.sales import SaleItem
from django.db import transaction
from django.utils.timezone import now
from django.utils import timezone
from datetime import timedelta
import json
import io
import re
from decimal import Decimal

# Import from your utility file
from easypharma.utility.purchase_import import process_csv_file
# from easypharma.utility.purchase_import import (normalize_column_name,find_column,looks_like_date,looks_like_integer,looks_like_decimal,
#                                     is_likely_product_name,is_likely_batch,infer_purchase_columns,
#                                     guess_invoice_number,guess_purchase_date,parse_decimal_value,
#                                     parse_integer_value,parse_expiry,process_csv_file)


class PurchaseEntryView(LoginRequiredMixin,View):
    template_name = 'purchase/entry.html'

    def get(self, request, invoice_id=None):
        suppliers = Supplier.objects.filter(tenant=request.tenant).order_by('name')
        products = Products.objects.filter(tenant=request.tenant).order_by('product_name')
        from easypharma.models.Items import ProductTax
        product_taxes = ProductTax.objects.filter(tenant=request.tenant)
        product_schedules = ProductSchedule.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True))
        drug_companies = DrugCompany.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True))
        product_contents = ProductContent.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('content_name')

        edit_data = None
        if invoice_id:
            try:
                invoice = PurchaseInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                items = []
                for item in invoice.items.all():
                    items.append({
                        'product_id': item.product.id,
                        'name': item.product.product_name,
                        'batch_number': item.batch_number,
                        'expiry_date': item.expiry_date.strftime('%Y-%m'),
                        'quantity': item.quantity,
                        'free_quantity': item.free_quantity,
                        'total_units': (item.quantity + item.free_quantity) * item.product.conversion_factor,
                        'purchase_price': float(item.purchase_price),
                        'tax_percentage': float(item.tax_percentage),
                        'tax_amount': float((item.quantity * item.purchase_price * item.tax_percentage) / 100),
                        'mrp': float(item.mrp),
                        'sale_price': float(item.sale_price),
                        'total': float(item.total_amount)
                    })
                edit_data = {
                    'id': invoice.id,
                    'supplier_id': invoice.supplier.id if invoice.supplier else '',
                    'invoice_number': invoice.invoice_number,
                    'purchase_date': invoice.purchase_date.strftime('%Y-%m-%d') if invoice.purchase_date else '',
                    'items': items,
                    'discount_amount': float(invoice.discount_amount),
                    'discount_percentage': float(invoice.discount_percentage or 0),
                    'payment_mode': invoice.payment_mode
                }
            except PurchaseInvoice.DoesNotExist:
                return redirect('purchase_list')
        edit_data = json.dumps(edit_data) if edit_data else None
        
        return render(request, self.template_name, {
            'suppliers': suppliers,
            'products': products,
            'product_taxes': product_taxes,
            'product_schedules': product_schedules,
            'drug_companies': drug_companies,
            'product_contents': product_contents,
            'edit_data': edit_data,
            'today': now().date()
        })

    def post(self, request, invoice_id=None):
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                # If editing, revert old stock first
                if invoice_id:
                    invoice = PurchaseInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                    for item in invoice.items.all():
                        
                        batch = StockBatch.objects.filter(
                            tenant=request.tenant, product=item.product, batch_number=item.batch_number
                        ).first()
                        if batch:
                            total_units = (item.quantity + item.free_quantity) * item.product.conversion_factor
                            batch.current_quantity -= total_units
                            if batch.current_quantity < 0: batch.current_quantity = 0
                            batch.save()
                    invoice.items.all().delete()
                else:
                    invoice = PurchaseInvoice(tenant=request.tenant, user=request.user)

                supplier = Supplier.objects.get(id=data['supplier_id'], tenant=request.tenant)
                invoice.supplier = supplier
                invoice.invoice_number = data['invoice_number']
                invoice.purchase_date = data['purchase_date']
                invoice.sub_total = data['sub_total']
                invoice.tax_amount = data['tax_amount']
                invoice.discount_percentage = data.get('discount_percentage', 0)
                invoice.discount_amount = data.get('discount_amount', 0)
                invoice.payment_mode = data.get('payment_mode', 'Cash')
                invoice.total_amount = data['total_amount']

                 # ── Generate voucher number (new invoices only) ───────────────
                if not invoice_id or not invoice.voucher_number:
                    invoice.voucher_number = PurchaseInvoice.generate_voucher_number(
                        tenant=request.tenant,
                        purchase_date=data.get('purchase_date')
                    )

                invoice.save()
                
                for item in data['items']:
                    product = Products.objects.get(id=item['product_id'], tenant=request.tenant)
                    # Note: PurchaseItem.save() handles stock addition
                    PurchaseItem.objects.create(
                        tenant=request.tenant,
                        purchase_invoice=invoice,
                        product=product,
                        batch_number=item['batch_number'],
                        expiry_date=item['expiry_date'] if '-' in item['expiry_date'] and len(item['expiry_date']) > 7 else item['expiry_date'] + "-01",
                        quantity=item['quantity'],
                        free_quantity=item.get('free_quantity', 0),
                        purchase_price=item['purchase_price'],
                        mrp=item['mrp'],
                        sale_price=item['sale_price'],
                        tax_percentage=item.get('tax_percentage', 0),
                        total_amount=item['total']
                    )
                
                from easypharma.models.accounting import SupplierLedger, ExpiryReturn
                
                applied_returns = data.get('applied_returns', [])
                total_credit_applied = sum(float(r['amount']) for r in applied_returns)

                if invoice_id:
                    SupplierLedger.objects.filter(tenant=request.tenant, reference_number=invoice.invoice_number, transaction_type='Purchase').delete()
                    
                    
                invoice.paid_amount = invoice.paid_amount + total_credit_applied
                invoice.save()

                for ret in applied_returns:
                    try:
                        exp_return = ExpiryReturn.objects.get(id=ret['return_id'], tenant=request.tenant)
                        if not exp_return.return_details:
                            exp_return.return_details = {}
                        if 'adjusted_invoices' not in exp_return.return_details:
                            exp_return.return_details['adjusted_invoices'] = []
                        
                        exp_return.return_details['adjusted_invoices'].append({
                            'id': invoice.id,
                            'amount': ret['amount']
                        })
                        exp_return.save()
                    except ExpiryReturn.DoesNotExist:
                        pass

                SupplierLedger.objects.create(
                    tenant=request.tenant,
                    supplier=supplier,
                    date=invoice.purchase_date,
                    transaction_type='Purchase',
                    reference_number=invoice.invoice_number,
                    debit=0,
                    credit=invoice.total_amount,
                    remarks="Purchase Invoice"
                )
                return JsonResponse({
                        'success': True,
                        'invoice_id': invoice.id,
                        'voucher_number': invoice.voucher_number,
                    })
                #return JsonResponse({'success': True, 'invoice_id': invoice.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

        # ── Invalidate caches after successful purchase save ──
        try:
            from easypharma.views.reports import invalidate_stock_cache
            from easypharma.views.sales import invalidate_pos_cache
            invalidate_stock_cache(request.tenant.id)
            invalidate_pos_cache(request.tenant.id)
        except Exception:
            pass  # Cache invalidation failure must not block the response

class PurchaseImportCSVView(View):
    def post(self, request):
        csv_file = request.FILES.get('csv_file')

        if not csv_file:
            return JsonResponse({'success': False, 'error': 'Please upload a CSV file.'}, status=400)


# Then continue with your existing code
        try:
            # Use the specialized parser we created for your CSV format
            data = process_csv_file(csv_file, request)
            return JsonResponse(data)

        except Exception as e:
            import traceback
            return JsonResponse({
                'success': False, 
                'error': str(e)
            })


class SupplierAutocomplete(LoginRequiredMixin,View):
    def get(self, request):
        query = request.GET.get('q', '')
        suppliers = Supplier.objects.filter(tenant=request.tenant, name__icontains=query)[:10]
        data = [{'id': s.id, 'name': s.name} for s in suppliers]
        return JsonResponse(data, safe=False)

class QuickCreateProductView(LoginRequiredMixin,View):
    """Inline product creation from CSV import."""
    def post(self, request):
        try:
            data = json.loads(request.body)
            product_name = data.get('product_name', '').strip()
            if not product_name:
                return JsonResponse({'success': False, 'error': 'Product name required'}, status=400)
            
            # Check if product already exists
            existing = Products.objects.filter(tenant=request.tenant, product_name__iexact=product_name).first()
            if existing:
                return JsonResponse({'success': True, 'product': {
                    'id': existing.id,
                    'name': existing.product_name
                }})
            
            # Get optional fields
            product_type = None
            if data.get('type_id'):
                try:
                    product_type = ProductType.objects.get(id=data.get('type_id'))
                except ProductType.DoesNotExist:
                    pass
            if not product_type:
                product_type = ProductType.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).first()
            
            schedule = None
            if data.get('schedule_id'):
                try:
                    schedule = ProductSchedule.objects.get(id=data.get('schedule_id'))
                except ProductSchedule.DoesNotExist:
                    pass
            
            company = None
            if data.get('company_id'):
                try:
                    company = DrugCompany.objects.get(id=data.get('company_id'))
                except DrugCompany.DoesNotExist:
                    pass
            
            # Create new product
            product = Products.objects.create(
                tenant=request.tenant,
                product_name=product_name,
                product_type=product_type,
                product_schedule=schedule,
                compny_name=company,
                product_packing=data.get('packing', ''),
                product_hsn_code=data.get('hsn', ''),
                conversion_factor=1
            )
            return JsonResponse({'success': True, 'product': {
                'id': product.id,
                'name': product.product_name
            }})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

class PurchaseListView(LoginRequiredMixin,View):
    template_name = 'purchase/list.html'
    ITEMS_PER_PAGE = 20

    def get(self, request):
        qs = (
            PurchaseInvoice.objects
            .filter(tenant=request.tenant)
            .select_related('supplier')
            .order_by('-purchase_date', '-created_at')
        )

        #invoices = PurchaseInvoice.objects.filter(tenant=request.tenant).select_related('supplier').order_by('-purchase_date','-created_at')

        # ── Search: voucher no / supplier invoice no / supplier name ─────────
        search_query = request.GET.get('q', '').strip()
        if search_query:
            qs = qs.filter(
                Q(voucher_number__icontains=search_query) |
                Q(invoice_number__icontains=search_query) |
                Q(supplier__name__icontains=search_query)
            )
        
        # ── Date range filter ─────────────────────────────────────────────────
        date_from = request.GET.get('date_from', '').strip()
        date_to   = request.GET.get('date_to',   '').strip()
        if date_from:
            qs = qs.filter(purchase_date__gte=date_from)
        if date_to:
            qs = qs.filter(purchase_date__lte=date_to)

              # ── Payment mode filter ───────────────────────────────────────────────
        payment_filter = request.GET.get('payment_mode', '').strip()
        if payment_filter in ('Cash', 'Credit'):
            qs = qs.filter(payment_mode=payment_filter)
 
        # ── Pagination ────────────────────────────────────────────────────────
        paginator   = Paginator(qs, self.ITEMS_PER_PAGE)
        page_number = request.GET.get('page', 1)
        page_obj    = paginator.get_page(page_number)

        return render(request, self.template_name, 
            {'page_obj':page_obj,
            'invoices':       page_obj,        # alias so existing template tag works
            'search_query':   search_query,
            'date_from':      date_from,
            'date_to':        date_to,
            'payment_filter': payment_filter,
            'total_count':    paginator.count,
        })

    def delete(self, request, invoice_id):
        try:
            with transaction.atomic():
                invoice = PurchaseInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                # When deleting an invoice, we must decrease stock
                for item in invoice.items.all():
                    from easypharma.models.stock import StockBatch
                    batch = StockBatch.objects.get(
                        tenant=request.tenant, 
                        product=item.product, 
                        batch_number=item.batch_number
                    )
                    total_units = (item.quantity + item.free_quantity) * item.product.conversion_factor
                    batch.current_quantity -= total_units
                    if batch.current_quantity < 0: batch.current_quantity = 0
                    batch.save()
                
                invoice.delete()
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class SupplierWisePurchaseReportView(LoginRequiredMixin,View):
    template_name = 'purchase/supplier_report.html'

    def get(self, request):
        suppliers = Supplier.objects.filter(tenant=request.tenant)
        return render(request, self.template_name, {'suppliers': suppliers})


class SupplierReportDataView(LoginRequiredMixin,View):
    def get(self, request, supplier_id):
        try:
            supplier = Supplier.objects.get(id=supplier_id, tenant=request.tenant)
            purchases = PurchaseInvoice.objects.filter(supplier=supplier)  # adjust model name if different

            data = {
                    'purchases': [
                        {
                            'id': p.id,
                            'invoice_number': p.invoice_number,
                            'date': str(p.purchase_date),
                            'total_amount': str(p.total_amount),
                            'items': [
                                {
                                    'product_name': item.product.product_name,
                                    'quantity': str(item.quantity),
                                    'unit_price': str(item.purchase_price), 
                                    'mrp': str(item.mrp),
                                    'batch_number': item.batch_number,
                                    'expiry_date': str(item.expiry_date),
                                    'tax_percentage': str(item.tax_percentage),
                                    'total_amount': str(item.total_amount),
                                }
                                for item in p.items.all()
                            ]                          
                        }                              
                        for p in purchases
                    ]                                 
                }
            return JsonResponse(data)

        except Supplier.DoesNotExist:
            return JsonResponse({'purchases': []}, status=404)


# ========== PURCHASE BILL EXPORT ==========


def _get_filtered_purchases(request):
    """Helper — return a filtered purchase invoice queryset based on GET params."""
    qs = (
        PurchaseInvoice.objects
        .filter(tenant=request.tenant)
        .select_related('supplier')
        .prefetch_related('items__product')
        .order_by('-purchase_date', '-created_at')
    )

    search_query = request.GET.get('q', '').strip()
    if search_query:
        qs = qs.filter(
            Q(voucher_number__icontains=search_query) |
            Q(invoice_number__icontains=search_query) |
            Q(supplier__name__icontains=search_query)
        )

    date_from = request.GET.get('date_from', '').strip()
    date_to   = request.GET.get('date_to',   '').strip()
    if date_from:
        qs = qs.filter(purchase_date__gte=date_from)
    if date_to:
        qs = qs.filter(purchase_date__lte=date_to)

    payment_filter = request.GET.get('payment_mode', '').strip()
    if payment_filter in ('Cash', 'Credit'):
        qs = qs.filter(payment_mode=payment_filter)

    return qs


class PurchaseExportCSVView(LoginRequiredMixin,View):
    """Export filtered purchase list as CSV — includes all transaction line items."""

    def get(self, request):
        qs = _get_filtered_purchases(request)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="purchase_bills.csv"'

        writer = csv.writer(response)
        # Header row
        writer.writerow([
            'Voucher No.', 'Purchase Date', 'Invoice No.', 'Supplier',
            'Payment Mode', 'Product Name', 'Packing',
            'Batch No.', 'Expiry Date', 'Qty', 'Free Qty',
            'Purchase Price (₹)', 'MRP (₹)', 'Sale Price (₹)',
            'GST %', 'Item Total (₹)',
            'Invoice Sub Total (₹)', 'Invoice GST (₹)',
            'Invoice Discount (₹)', 'Invoice Total (₹)',
        ])

        for invoice in qs:
            items = invoice.items.all()
            if items.exists():
                for item in items:
                    writer.writerow([
                        invoice.voucher_number or '—',
                        invoice.purchase_date.strftime('%d/%m/%Y') if invoice.purchase_date else '—',
                        invoice.invoice_number,
                        invoice.supplier.name if invoice.supplier else '—',
                        invoice.payment_mode,
                        item.product.product_name,
                        item.product.product_packing or '—',
                        item.batch_number,
                        item.expiry_date.strftime('%m/%Y') if item.expiry_date else '—',
                        item.quantity,
                        item.free_quantity,
                        float(item.purchase_price),
                        float(item.mrp),
                        float(item.sale_price),
                        float(item.tax_percentage),
                        float(item.total_amount),
                        float(invoice.sub_total),
                        float(invoice.tax_amount),
                        float(invoice.discount_amount),
                        float(invoice.total_amount),
                    ])
            else:
                # Invoice with no items — write header row only
                writer.writerow([
                    invoice.voucher_number or '—',
                    invoice.purchase_date.strftime('%d/%m/%Y') if invoice.purchase_date else '—',
                    invoice.invoice_number,
                    invoice.supplier.name if invoice.supplier else '—',
                    invoice.payment_mode,
                    '—', '—', '—', '—', '—', '—', '—', '—', '—', '—', '—',
                    float(invoice.sub_total),
                    float(invoice.tax_amount),
                    float(invoice.discount_amount),
                    float(invoice.total_amount),
                ])

        return response


class PurchaseExportPDFView(LoginRequiredMixin,View):
    """Export filtered purchase list as PDF — all transaction data."""

    template_name = 'purchase/purchase_export_pdf.html'

    def get(self, request):
        qs = _get_filtered_purchases(request)

        invoices_data = []
        for invoice in qs:
            items = []
            for item in invoice.items.all():
                items.append({
                    'product_name': item.product.product_name,
                    'packing': item.product.product_packing or '—',
                    'batch_number': item.batch_number,
                    'expiry_date': item.expiry_date.strftime('%m/%Y') if item.expiry_date else '—',
                    'quantity': item.quantity,
                    'free_quantity': item.free_quantity,
                    'purchase_price': float(item.purchase_price),
                    'mrp': float(item.mrp),
                    'sale_price': float(item.sale_price),
                    'tax_percentage': float(item.tax_percentage),
                    'total_amount': float(item.total_amount),
                })
            invoices_data.append({
                'voucher_number': invoice.voucher_number or '—',
                'purchase_date': invoice.purchase_date.strftime('%d/%m/%Y') if invoice.purchase_date else '—',
                'invoice_number': invoice.invoice_number,
                'supplier_name': invoice.supplier.name if invoice.supplier else '—',
                'payment_mode': invoice.payment_mode,
                'sub_total': float(invoice.sub_total),
                'tax_amount': float(invoice.tax_amount),
                'discount_amount': float(invoice.discount_amount),
                'total_amount': float(invoice.total_amount),
                'items': items,
            })

        # Overall totals
        grand_total = sum(i['total_amount'] for i in invoices_data)
        grand_sub_total = sum(i['sub_total'] for i in invoices_data)
        grand_tax = sum(i['tax_amount'] for i in invoices_data)
        grand_discount = sum(i['discount_amount'] for i in invoices_data)

        context = {
            'invoices_data': invoices_data,
            'grand_total': grand_total,
            'grand_sub_total': grand_sub_total,
            'grand_tax': grand_tax,
            'grand_discount': grand_discount,
            'pharmacy': request.tenant,
            'date_from': request.GET.get('date_from', ''),
            'date_to': request.GET.get('date_to', ''),
            'search_query': request.GET.get('q', ''),
            'total_invoices': len(invoices_data),
        }

        return render_to_pdf(self.template_name, context, filename='purchase_bills.pdf')

class ProductBatchHistoryView(LoginRequiredMixin,View):
    def get(self, request):
        product_id = request.GET.get('product_id')
        if not product_id:
            return JsonResponse([], safe=False)
        
        batches = (
            StockBatch.objects
            .filter(tenant=request.tenant, product_id=product_id)
            .order_by('-expiry_date')
            .values('batch_number', 'expiry_date', 'mrp', 'purchase_price', 'current_quantity')[:10]
        )
        result = [
            {
                'batch_number': b['batch_number'],
                'expiry_date':  b['expiry_date'].strftime('%Y-%m') if b['expiry_date'] else '',
                'mrp':          float(b['mrp'] or 0),
                'purchase_price': float(b['purchase_price'] or 0),
                'stock_quantity': b['current_quantity'],
            }
            for b in batches
        ]
        return JsonResponse(result, safe=False)


class SmartPurchaseSuggestPageView(LoginRequiredMixin,View):
    """Renders the HTML page."""
    template_name = 'purchase/purchase_suggestion.html'

    def get(self, request):
        return render(request, self.template_name)


class SmartPurchaseSuggestAPIView(LoginRequiredMixin,View):
    """
    Suggests products to purchase today based on:
    - Average daily sales calculated over the actual number of active sale days
      (not a fixed 30-day divisor, so new products with limited history are handled correctly)
    - Current stock vs projected need (avg_daily_sale * reorder_days)
    - Best supplier (lowest last purchase price = highest profit) vs last used supplier
 
    Supports pagination via ?page=<n>&page_size=<n> query params.
    No caching is applied — data is always computed fresh on each request.
    """
 
    DAYS_FOR_AVG = 30          # window to look back for sales history
    REORDER_DAYS = 7           # how many days of stock you want to maintain
    DEFAULT_PAGE_SIZE = 20
    MAX_PAGE_SIZE = 100
 
    def get(self, request):
        tenant = request.tenant
 
        cutoff_date = timezone.now() - timedelta(days=self.DAYS_FOR_AVG)
 
        # Step 1: Get total sold + first sale date per product within the window
        sales_data = (
            SaleItem.objects
            .filter(
                tenant=tenant,
                sale_invoice__created_at__gte=cutoff_date
            )
            .values('product_id')
            .annotate(
                total_sold=Sum('quantity'),
                first_sale_date=Min('sale_invoice__created_at')
            )
        )
 
        sales_map = {}
        for row in sales_data:
            days_active = (timezone.now() - row['first_sale_date']).days
            days_active = max(days_active, 1)  # avoid division by zero for same-day sales
            sales_map[row['product_id']] = {
                'total_sold': row['total_sold'],
                'days_active': days_active,
            }
 
        if not sales_map:
            return JsonResponse({
                'count': 0,
                'page': 1,
                'page_size': self.DEFAULT_PAGE_SIZE,
                'total_pages': 0,
                'has_next': False,
                'has_previous': False,
                'results': [],
            }, safe=False)
 
        # Step 2: Get current stock for these products
        products_qs = (
            Products.objects
            .filter(tenant=tenant, id__in=sales_map.keys())
            .annotate(total_stock=Sum('batches__current_quantity'))
        )
 
        suggestions = []
 
        for product in products_qs:
            total_stock = product.total_stock or 0
 
            data = sales_map.get(product.id)
            total_sold = data['total_sold']
            days_active = data['days_active']
 
            avg_daily_sale = total_sold / days_active
            projected_need = avg_daily_sale * self.REORDER_DAYS
 
            # Only suggest if current stock is less than projected need for reorder period
            if total_stock >= projected_need:
                continue
 
            reorder_qty = round(projected_need - total_stock)
            if reorder_qty <= 0:
                continue
 
            purchase_items = (
                PurchaseItem.objects
                .filter(tenant=tenant, product=product)
                .select_related('purchase_invoice', 'purchase_invoice__supplier')
                .order_by('-purchase_invoice__purchase_date')
            )
 
            if not purchase_items.exists():
                suggestions.append({
                    'id': product.id,
                    'name': product.product_name,
                    'packing': product.product_packing,
                    'conversion_factor': product.conversion_factor,
                    'total_stock': total_stock,
                    'avg_daily_sale': round(avg_daily_sale, 2),
                    'reorder_qty': reorder_qty,
                    'last_purchase': None,
                    'last_supplier': None,
                    'last_purchase_price': None,
                    'best_supplier': None,
                    'best_purchase_price': None,
                    'profit_difference': None,
                    'compare_reason': "No previous purchase history found for this product. Please select a supplier.",
                    'suggested_supplier': None,
                })
                continue
 
            last_item = purchase_items.first()
            last_supplier = last_item.purchase_invoice.supplier
            last_price = last_item.purchase_price
            last_date = last_item.purchase_invoice.purchase_date
 
            supplier_latest_prices = {}
            for item in purchase_items:
                supplier = item.purchase_invoice.supplier
                if supplier.id not in supplier_latest_prices:
                    supplier_latest_prices[supplier.id] = {
                        'supplier': supplier,
                        'purchase_price': item.purchase_price,
                        'purchase_date': item.purchase_invoice.purchase_date,
                    }
 
            best_entry = min(
                supplier_latest_prices.values(),
                key=lambda x: x['purchase_price']
            )
            best_supplier = best_entry['supplier']
            best_price = best_entry['purchase_price']
 
            profit_diff = last_price - best_price
 
            if best_supplier.id != last_supplier.id and profit_diff > 0:
                compare_reason = (
                    f"Last time you purchased from '{last_supplier.name}' at ₹{last_price}/unit. "
                    f"'{best_supplier.name}' offers it at ₹{best_price}/unit "
                    f"(₹{profit_diff} more profit per unit)."
                )
                suggested_supplier_data = {
                    'id': best_supplier.id,
                    'name': best_supplier.name,
                    'purchase_price': float(best_price),
                }
            else:
                compare_reason = f"'{last_supplier.name}' is already offering the best price (₹{last_price}/unit)."
                suggested_supplier_data = {
                    'id': last_supplier.id,
                    'name': last_supplier.name,
                    'purchase_price': float(last_price),
                }
 
            suggestions.append({
                'id': product.id,
                'name': product.product_name,
                'packing': product.product_packing,
                'conversion_factor': product.conversion_factor,
                'total_stock': total_stock,
                'avg_daily_sale': round(avg_daily_sale, 2),
                'reorder_qty': reorder_qty,
                'last_purchase': last_date.strftime('%Y-%m-%d') if last_date else None,
                'last_supplier': {
                    'id': last_supplier.id,
                    'name': last_supplier.name,
                },
                'last_purchase_price': float(last_price),
                'best_supplier': {
                    'id': best_supplier.id,
                    'name': best_supplier.name,
                },
                'best_purchase_price': float(best_price),
                'profit_difference': float(profit_diff),
                'compare_reason': compare_reason,
                'suggested_supplier': suggested_supplier_data,
            })
 
        # Most urgent first: highest sale velocity vs lowest remaining stock
        suggestions.sort(key=lambda x: x['avg_daily_sale'], reverse=True)
 
        # ---- Pagination ----
        try:
            page_number = int(request.GET.get('page', 1))
        except (TypeError, ValueError):
            page_number = 1
 
        try:
            page_size = int(request.GET.get('page_size', self.DEFAULT_PAGE_SIZE))
        except (TypeError, ValueError):
            page_size = self.DEFAULT_PAGE_SIZE
 
        page_size = max(1, min(page_size, self.MAX_PAGE_SIZE))
 
        paginator = Paginator(suggestions, page_size)
        page_number = max(1, min(page_number, paginator.num_pages or 1))
        page_obj = paginator.get_page(page_number)
 
        return JsonResponse({
            'count': paginator.count,
            'page': page_obj.number,
            'page_size': page_size,
            'total_pages': paginator.num_pages,
            'has_next': page_obj.has_next(),
            'has_previous': page_obj.has_previous(),
            'results': list(page_obj.object_list),
        }, safe=False)


class OpeningStockListView(LoginRequiredMixin, View):
    template_name = 'purchase/opening_list.html'  # We'll create this
    ITEMS_PER_PAGE = 20

    def get(self, request):
        qs = OpeningStock.objects.filter(tenant=request.tenant).order_by('-opening_stock_date')

        search_query = request.GET.get('q', '').strip()
        if search_query:
            qs = qs.filter(voucher_number__icontains=search_query)

        date_from = request.GET.get('date_from', '').strip()
        date_to = request.GET.get('date_to', '').strip()
        if date_from:
            qs = qs.filter(opening_stock_date__gte=date_from)
        if date_to:
            qs = qs.filter(opening_stock_date__lte=date_to)

        paginator = Paginator(qs, self.ITEMS_PER_PAGE)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        return render(request, self.template_name, {
            'page_obj': page_obj,
            'opening_stocks': page_obj,
            'search_query': search_query,
            'date_from': date_from,
            'date_to': date_to,
            'total_count': paginator.count,
        })


class OpeningStockEntryView(LoginRequiredMixin, View):
    template_name = 'purchase/opening_entry.html'

    def get(self, request, stock_id=None):
        products = Products.objects.filter(tenant=request.tenant).order_by('product_name')
        product_taxes = ProductTax.objects.filter(tenant=request.tenant)
        product_schedules = ProductSchedule.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True))
        drug_companies = DrugCompany.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True))
        product_contents = ProductContent.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('content_name')

        edit_data = None
        if stock_id:
            try:
                stock = OpeningStock.objects.get(id=stock_id, tenant=request.tenant)
                items = [{
                    'product_id': item.product.id,
                    'name': item.product.product_name,
                    'batch_number': item.batch_number,
                    'expiry_date': item.expiry_date.strftime('%Y-%m'),
                    'quantity': item.quantity,
                    'purchase_price': float(item.purchase_price),
                    'mrp': float(item.mrp),
                    'tax_percentage': float(item.tax_percentage),
                    'total': float(item.total_amount)
                } for item in stock.items.all()]

                edit_data = {
                    'id': stock.id,
                    'voucher_number': stock.voucher_number,
                    'opening_stock_date': stock.opening_stock_date.strftime('%Y-%m-%d') if stock.opening_stock_date else '',
                    'items': items,
                    'sub_total': float(stock.sub_total),
                    'tax_amount': float(stock.tax_amount),
                    'discount_amount': float(stock.discount_amount),
                    'total_amount': float(stock.total_amount),
                }
            except OpeningStock.DoesNotExist:
                return redirect('opening_stock_list')

        return render(request, self.template_name, {
            'products': products,
            'product_taxes': product_taxes,
            'product_schedules': product_schedules,
            'drug_companies': drug_companies,
            'product_contents': product_contents,
            'edit_data': json.dumps(edit_data) if edit_data else None,
            'today': now().date()
        })

    def post(self, request, stock_id=None):
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                if stock_id:
                    # Revert old stock
                    stock = OpeningStock.objects.get(id=stock_id, tenant=request.tenant)
                    for item in stock.items.all():
                        batch = StockBatch.objects.filter(
                            tenant=request.tenant, 
                            product=item.product, 
                            batch_number=item.batch_number
                        ).first()
                        if batch:
                            batch.current_quantity -= item.quantity * item.product.conversion_factor
                            if batch.current_quantity < 0:
                                batch.current_quantity = 0
                            batch.save()
                    stock.items.all().delete()
                else:
                    stock = OpeningStock(tenant=request.tenant)

                stock.opening_stock_date = data['opening_stock_date']
                stock.sub_total = data['sub_total']
                stock.tax_amount = data['tax_amount']
                stock.discount_percentage = data.get('discount_percentage', 0)
                stock.discount_amount = data.get('discount_amount', 0)
                stock.total_amount = data['total_amount']

                if not stock_id or not stock.voucher_number:
                    stock.voucher_number = OpeningStock.generate_voucher_number(
                        tenant=request.tenant,
                        opening_stock_date=data['opening_stock_date']
                    )
                stock.save()

                for item in data['items']:
                    product = Products.objects.get(id=item['product_id'], tenant=request.tenant)
                    OpeningStockItem.objects.create(
                        tenant=request.tenant,
                        opening_stock=stock,
                        product=product,
                        batch_number=item['batch_number'],
                        expiry_date=item['expiry_date'] + "-01" if len(item['expiry_date']) == 7 else item['expiry_date'],
                        quantity=item['quantity'],
                        purchase_price=item['purchase_price'],
                        mrp=item['mrp'],
                        tax_percentage=item.get('tax_percentage', 0),
                        total_amount=item['total']
                    )

                return JsonResponse({
                    'success': True,
                    'stock_id': stock.id,
                    'voucher_number': stock.voucher_number,
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)