from django.views import View
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.db.models import Q
from easypharma.models.Items import (Products,DrugCompany, ProductContent, 
                                     ProductSchedule,
                                     ProductTax, ProductType)

from easypharma.models.purchase_invoice import Supplier, PurchaseInvoice, PurchaseItem
from easypharma.models.stock import StockBatch
from django.db import transaction
from django.utils.timezone import now
import json

class PurchaseEntryView(View):
    template_name = 'purchase/entry.html'

    def get(self, request, invoice_id=None):
        suppliers = Supplier.objects.filter(tenant=request.tenant).order_by('name')
        products = Products.objects.filter(tenant=request.tenant).order_by('product_name')
        from easypharma.models.Items import ProductTax
        product_taxes = ProductTax.objects.filter(tenant=request.tenant)
        product_schedules = ProductSchedule.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True))
        drug_companies = DrugCompany.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True))

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

                # If there are applied returns, create a ledger entry representing the adjustment (payment) against this invoice?
                # Actually, ExpiryReturn ALREADY created a Debit in the ledger when it was created!
                # We do NOT create another ledger entry here because the return is already in the ledger.
                # Applying it just links them and reduces the outstanding balance.

                return JsonResponse({'success': True, 'invoice_id': invoice.id})
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({'success': False, 'error': str(e)})

class SupplierAutocomplete(View):
    def get(self, request):
        query = request.GET.get('q', '')
        suppliers = Supplier.objects.filter(tenant=request.tenant, name__icontains=query)[:10]
        data = [{'id': s.id, 'name': s.name} for s in suppliers]
        return JsonResponse(data, safe=False)

class PurchaseListView(View):
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


class SupplierWisePurchaseReportView(View):
    template_name = 'purchase/supplier_report.html'

    def get(self, request):
        suppliers = Supplier.objects.filter(tenant=request.tenant)
        return render(request, self.template_name, {'suppliers': suppliers})


from django.http import JsonResponse

class SupplierReportDataView(View):
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

import csv
from django.http import HttpResponse
from easypharma.views.reports import render_to_pdf


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


class PurchaseExportCSVView(View):
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


class PurchaseExportPDFView(View):
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
