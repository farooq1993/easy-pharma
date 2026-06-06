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
import io
import re
from decimal import Decimal

def normalize_column_name(value):
    if value is None:
        return ''
    return re.sub(r'[^a-z0-9]+', ' ', str(value).strip().lower())


def find_column(headers, names):
    for name in names:
        for idx, header in enumerate(headers):
            if name in header:
                return idx
    return None


def looks_like_date(value):
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    text = text.replace('/', '-').replace('.', '-').strip()
    if re.match(r'^[0-9]{4}-[0-9]{1,2}$', text):
        return True
    if re.match(r'^[0-9]{1,2}-[0-9]{1,2}-[0-9]{2,4}$', text):
        return True
    if re.match(r'^[0-9]{6,8}$', text):
        return True
    return False


def looks_like_integer(value):
    if value is None:
        return False
    text = str(value).strip().replace(',', '')
    if not text:
        return False
    return re.fullmatch(r'[-+]?[0-9]+', text) is not None


def looks_like_decimal(value):
    if value is None:
        return False
    text = str(value).strip().replace(',', '')
    if not text:
        return False
    return re.fullmatch(r'[-+]?[0-9]*\.?[0-9]+', text) is not None


def is_likely_product_name(value):
    if value is None:
        return False
    text = str(value).strip()
    if not text:
        return False
    if looks_like_date(text) or looks_like_decimal(text) or looks_like_integer(text):
        return False
    if ' ' in text and any(c.isalpha() for c in text):
        return True
    letters = sum(1 for c in text if c.isalpha())
    digits = sum(1 for c in text if c.isdigit())
    return letters >= 3 and digits <= letters


def is_likely_batch(value):
    if value is None:
        return False
    text = str(value).strip()
    if not text or ' ' in text:
        return False
    has_alpha = any(c.isalpha() for c in text)
    has_digit = any(c.isdigit() for c in text)
    return has_alpha and has_digit and 3 <= len(text) <= 15


def infer_purchase_columns(rows):
    sample_rows = rows[:min(len(rows), 10)]
    max_cols = max((len(row) for row in sample_rows), default=0)
    stats = [
        {
            'product': 0,
            'batch': 0,
            'expiry': 0,
            'quantity': 0,
            'decimal': 0,
            'integer': 0,
            'text': 0,
            'long_text': 0,
            'date': 0,
        }
        for _ in range(max_cols)
    ]

    for row in sample_rows:
        for col in range(max_cols):
            value = str(row[col]).strip() if col < len(row) else ''
            if not value:
                continue
            if looks_like_date(value):
                stats[col]['date'] += 1
            if looks_like_decimal(value):
                stats[col]['decimal'] += 1
            if looks_like_integer(value):
                stats[col]['integer'] += 1
            if is_likely_product_name(value):
                stats[col]['product'] += 1
            if is_likely_batch(value):
                stats[col]['batch'] += 1
            if any(c.isalpha() for c in value) and ' ' in value:
                stats[col]['text'] += 1
            if len(value) >= 10:
                stats[col]['long_text'] += 1

    def choose_best(key, exclude=None):
        exclude = exclude or []
        candidates = [i for i in range(max_cols) if i not in exclude]
        if not candidates:
            return None
        candidates.sort(key=lambda i: (stats[i][key], stats[i].get('text', 0), stats[i].get('long_text', 0)), reverse=True)
        return candidates[0] if stats[candidates[0]][key] > 0 else None

    product_idx = choose_best('product') or choose_best('text')
    expiry_idx = choose_best('date', exclude=[product_idx])
    batch_idx = choose_best('batch', exclude=[product_idx, expiry_idx])
    qty_idx = choose_best('integer', exclude=[product_idx, expiry_idx, batch_idx])
    purchase_price_idx = choose_best('decimal', exclude=[product_idx, expiry_idx, batch_idx, qty_idx])
    mrp_idx = choose_best('decimal', exclude=[product_idx, expiry_idx, batch_idx, qty_idx, purchase_price_idx])
    sale_price_idx = choose_best('decimal', exclude=[product_idx, expiry_idx, batch_idx, qty_idx, purchase_price_idx, mrp_idx])

    return {
        'product_idx': product_idx,
        'batch_idx': batch_idx,
        'expiry_idx': expiry_idx,
        'qty_idx': qty_idx,
        'free_idx': None,
        'purchase_price_idx': purchase_price_idx,
        'mrp_idx': mrp_idx,
        'sale_price_idx': sale_price_idx,
        'total_idx': None,
        'invoice_idx': None,
        'date_idx': None,
        'data_start': 0
    }


def guess_invoice_number(rows):
    for row in rows[:3]:
        for cell in row:
            text = str(cell).strip()
            if not text:
                continue
            if looks_like_date(text) or looks_like_decimal(text) or looks_like_integer(text):
                continue
            if re.search(r'[A-Za-z]+\d+|\d{5,}', text):
                return text
    return None


def guess_purchase_date(rows):
    for row in rows[:3]:
        for cell in row:
            text = str(cell).strip()
            if looks_like_date(text):
                parsed = parse_expiry(text)
                if parsed:
                    if len(parsed) == 7 and parsed[4] == '-':
                        return f"{parsed}-01"
                    return parsed
                text = text.replace('/', '-').replace('.', '-').strip()
                parts = text.split('-')
                if len(parts) == 3:
                    day, month, year = parts[0], parts[1], parts[2]
                    if len(year) == 2:
                        year = '20' + year
                    if len(day) == 2 and len(month) == 2 and len(year) == 4:
                        return f"{year}-{month}-{day}"
                elif len(parts) == 2:
                    if len(parts[0]) == 4:
                        year, month = parts[0], parts[1]
                        return f"{year}-{month}-01"
                    else:
                        month, year = parts[0], parts[1]
                        if len(year) == 2:
                            year = '20' + year
                        return f"{year}-{month}-01"
    return None


def parse_decimal_value(value, default=Decimal('0')):
    if value is None or str(value).strip() == '':
        return default
    value = str(value).replace(',', '').strip()
    try:
        return Decimal(value)
    except Exception:
        try:
            return Decimal(str(float(value)))
        except Exception:
            return default


def parse_integer_value(value, default=0):
    if value is None or str(value).strip() == '':
        return default
    try:
        return int(float(str(value).replace(',', '').strip()))
    except Exception:
        return default


def parse_expiry(value):
    if not value:
        return ''
    text = str(value).strip()
    # Handle 8-digit format: DDMMYYYY
    if len(text) == 8 and text.isdigit():
        day = text[0:2]
        month = text[2:4]
        year = text[4:8]
        if int(month) < 1 or int(month) > 12:
            return ''
        return f'{year}-{month}'
    
    # Normalize formats like DD/MM/YYYY, DD-MM-YYYY, YYYY-MM, MM/YYYY, YYYYMM
    text = text.replace('/', '-').replace('.', '-').strip()
    parts = text.split('-')
    if len(parts) == 3:
        year, month = parts[2], parts[1]
    elif len(parts) == 2:
        if len(parts[0]) == 4:
            year, month = parts[0], parts[1]
        else:
            year, month = parts[1], parts[0]
    elif len(parts) == 1 and len(parts[0]) == 6:
        year, month = parts[0][:4], parts[0][4:6]
    else:
        return ''
    if len(month) == 1:
        month = '0' + month
    if len(year) == 2:
        year = '20' + year
    if not (year.isdigit() and month.isdigit()):
        return ''
    if int(month) < 1 or int(month) > 12:
        return ''
    return f'{year}-{month}'


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
                return JsonResponse({
                        'success': True,
                        'invoice_id': invoice.id,
                        'voucher_number': invoice.voucher_number,
                    })
                #return JsonResponse({'success': True, 'invoice_id': invoice.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

class PurchaseImportCSVView(View):
    def post(self, request):
        csv_file = request.FILES.get('csv_file')

        if not csv_file:
            return JsonResponse({'success': False, 'error': 'Please upload a CSV file.'}, status=400)

        try:
            try:
                file_data = csv_file.read().decode('utf-8-sig')
            except UnicodeDecodeError:
                try:
                    file_data = csv_file.read().decode('latin-1')
                except Exception:
                    return JsonResponse({'success': False, 'error': 'Unable to decode CSV file. Use UTF-8 encoding.'}, status=400)

            rows = []
            try:
                reader = csv.reader(io.StringIO(file_data))
                rows = [r for r in reader if any(cell.strip() for cell in r)]
            except Exception:
                return JsonResponse({'success': False, 'error': 'Invalid CSV file format.'}, status=400)

            if not rows:
                return JsonResponse({'success': False, 'error': 'CSV file is empty.'}, status=400)

            headers = [normalize_column_name(h) for h in rows[0]]
            product_idx = find_column(headers, ['product', 'product name', 'item', 'item name', 'description', 'drug', 'medicine', 'brand', 'generic', 'molecule'])
            batch_idx = find_column(headers, ['batch', 'batch no', 'batch_number', 'batch number'])
            expiry_idx = find_column(headers, ['expiry', 'exp', 'expiry_date', 'exp_date', 'expiry date'])
            qty_idx = find_column(headers, ['qty', 'quantity', 'pack', 'packs', 'units', 'nos', 'pcs', 'pieces'])
            free_idx = find_column(headers, ['free', 'free_qty', 'free quantity'])
            purchase_price_idx = find_column(headers, ['purchase price', 'purchase_price', 'rate', 'cost', 'price', 'unit cost', 'buy price', 'invoice rate', 'net price'])
            mrp_idx = find_column(headers, ['mrp'])
            sale_price_idx = find_column(headers, ['sale_price', 'sale price', 'sale'])
            total_idx = find_column(headers, ['total', 'amount', 'value', 'line total', 'gross'])
            invoice_idx = find_column(headers, ['invoice', 'bill no', 'invoice number', 'voucher', 'bill number'])
            date_idx = find_column(headers, ['date', 'purchase_date', 'purchase date', 'invoice date'])

            data_rows = rows[1:]
            headerless = False
            if product_idx is None or qty_idx is None or purchase_price_idx is None:
                inferred = infer_purchase_columns(rows)
                if inferred['product_idx'] is not None and inferred['qty_idx'] is not None and inferred['purchase_price_idx'] is not None:
                    product_idx = inferred['product_idx']
                    batch_idx = inferred['batch_idx']
                    expiry_idx = inferred['expiry_idx']
                    qty_idx = inferred['qty_idx']
                    free_idx = inferred['free_idx']
                    purchase_price_idx = inferred['purchase_price_idx']
                    mrp_idx = inferred['mrp_idx']
                    sale_price_idx = inferred['sale_price_idx']
                    total_idx = inferred['total_idx']
                    invoice_idx = inferred['invoice_idx']
                    date_idx = inferred['date_idx']

                    first_row = rows[0]
                    header_candidate_count = sum(
                        1 for cell in first_row
                        if str(cell).strip() and not looks_like_integer(cell) and not looks_like_decimal(cell) and not looks_like_date(cell)
                    )
                    if header_candidate_count >= max(2, len(first_row) // 3):
                        data_rows = rows[1:]
                    else:
                        data_rows = rows
                        headerless = True
                else:
                    return JsonResponse({
                        'success': False,
                        'error': f'CSV header not recognized. Missing columns: {", ".join([c for c in ["product" if product_idx is None else None, "quantity" if qty_idx is None else None, "purchase price" if purchase_price_idx is None else None] if c])}.',
                        'detected_headers': headers,
                        'required_columns': ['product', 'quantity', 'purchase price']
                    }, status=400)

            items = []
            missing_products = []
            invoice_number = None
            purchase_date = None
            supplier_name = None

            if headerless:
                invoice_number = guess_invoice_number(rows)
                purchase_date = guess_purchase_date(rows)

            for row_number, row in enumerate(data_rows, start=(2 if not headerless else 1)):
                if product_idx >= len(row):
                    continue
                product_name = str(row[product_idx]).strip()
                if not product_name:
                    continue

                if invoice_number is None and invoice_idx is not None and invoice_idx < len(row):
                    invoice_number = str(row[invoice_idx]).strip() or invoice_number
                if purchase_date is None and date_idx is not None and date_idx < len(row):
                    purchase_date = str(row[date_idx]).strip() or purchase_date
                if supplier_name is None:
                    supplier_name = None

                batch_number = str(row[batch_idx]).strip() if batch_idx is not None and batch_idx < len(row) else ''
                expiry_text = str(row[expiry_idx]).strip() if expiry_idx is not None and expiry_idx < len(row) else ''
                expiry_date = parse_expiry(expiry_text)
                quantity = parse_integer_value(row[qty_idx])
                free_quantity = parse_integer_value(row[free_idx]) if free_idx is not None and free_idx < len(row) else 0
                purchase_price = parse_decimal_value(row[purchase_price_idx])
                mrp = parse_decimal_value(row[mrp_idx]) if mrp_idx is not None and mrp_idx < len(row) else Decimal('0')
                sale_price = parse_decimal_value(row[sale_price_idx]) if sale_price_idx is not None and sale_price_idx < len(row) else Decimal('0')
                total_amount = parse_decimal_value(row[total_idx]) if total_idx is not None and total_idx < len(row) else Decimal('0')

                if sale_price == 0 and mrp > 0:
                    sale_price = mrp
                if mrp == 0:
                    mrp = purchase_price
                if total_amount == 0:
                    total_amount = (purchase_price * quantity) + Decimal('0')

                product = Products.objects.filter(tenant=request.tenant, product_name__iexact=product_name).first()
                if not product:
                    product = Products.objects.filter(tenant=request.tenant, product_name__icontains=product_name).first()

                if not product:
                    missing_products.append({
                        'row': row_number,
                        'product': product_name,
                        'message': 'Product not found in master data. Please create it first.'
                    })
                    continue

                items.append({
                    'product_id': product.id,
                    'name': product.product_name,
                    'packing': product.product_packing or '',
                    'conversion_factor': product.conversion_factor or 1,
                    'batch_number': batch_number or '',
                    'expiry_date': expiry_date or '',
                    'quantity': quantity,
                    'free_quantity': free_quantity,
                    'total_units': (quantity + free_quantity) * (product.conversion_factor or 1),
                    'purchase_price': float(purchase_price),
                    'tax_percentage': float(product.product_tax.tax_rate if product.product_tax else 0),
                    'tax_amount': float((purchase_price * quantity) * (product.product_tax.tax_rate if product.product_tax else 0) / 100),
                    'mrp': float(mrp),
                    'sale_price': float(sale_price),
                    'total': float(total_amount)
                })

            return JsonResponse({
                'success': True,
                'invoice_number': invoice_number,
                'purchase_date': purchase_date,
                'supplier_name': supplier_name,
                'items': items,
                'missing_products': missing_products
            })
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

class QuickCreateProductView(View):
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
