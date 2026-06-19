import re
from decimal import Decimal
import csv
import io
from easypharma.models.Items import Products
from easypharma.models.purchase_invoice import PurchaseInvoice

def parse_integer_value(value, default=0):
    if not value:
        return default
    text = str(value).strip().split()[0]
    text = re.sub(r'[^0-9.-]', '', text)
    try:
        return int(float(text))
    except:
        return default

def parse_decimal_value(value, default=Decimal('0')):
    if not value:
        return default
    text = str(value).strip().split()[0]
    text = re.sub(r'[^0-9.-]', '', text)
    try:
        return Decimal(text)
    except:
        try:
            return Decimal(str(float(text)))
        except:
            return default

def parse_expiry(value):
    if not value:
        return None
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        day = text[0:2]
        month = text[2:4]
        year = text[4:8]
        if 1 <= int(month) <= 12:
            return f'{year}-{month}-{day}'
    return None

def infer_purchase_columns(rows):
    return {
        'product_idx': 5,
        'batch_idx': 8,
        'expiry_idx': 9,
        'qty_idx': 15,
        'free_idx': 16,
        'purchase_price_idx': 10,
        'mrp_idx': 12,
    }

def process_csv_file(csv_file, request):
    try:
        file_data = csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        file_data = csv_file.read().decode('latin-1')

    reader = csv.reader(io.StringIO(file_data))
    rows = [r for r in reader if any(cell.strip() for cell in r)]

    if not rows:
        return {'success': False, 'error': 'CSV file is empty.'}

    inferred = infer_purchase_columns(rows)
    items = []
    missing_products = []
    invoice_number = None

    for row in rows[:3]:
        for cell in row:
            if re.search(r'INV\d+', str(cell)):
                invoice_number = str(cell).strip()
                break
        if invoice_number:
            break
    # === IMPORTANT: Check if Invoice already exists ===
    if invoice_number:
        existing = PurchaseInvoice.objects.filter(
            tenant=request.tenant, 
            invoice_number=invoice_number
        ).exists()
        
        if existing:
            return {
                'success': False,
                'error': f"Invoice {invoice_number} is already imported in the system."
            }
    for row_number, row in enumerate(rows, start=1):
        if len(row) < 17 or row[0] != 'T':
            continue

        product_name = str(row[inferred['product_idx']]).strip()
        if not product_name:
            continue

        batch_number = str(row[inferred['batch_idx']]).strip() if len(row) > inferred['batch_idx'] else ''
        expiry_text = str(row[inferred['expiry_idx']]).strip() if len(row) > inferred['expiry_idx'] else ''
        
        quantity = parse_integer_value(row[inferred['qty_idx']] if len(row) > inferred['qty_idx'] else 0)
        free_quantity = parse_integer_value(row[inferred['free_idx']] if len(row) > inferred['free_idx'] else 0)

        purchase_price = parse_decimal_value(row[inferred['purchase_price_idx']] if len(row) > inferred['purchase_price_idx'] else 0)
        mrp = parse_decimal_value(row[inferred['mrp_idx']] if len(row) > inferred['mrp_idx'] else 0)

        expiry_date = parse_expiry(expiry_text)

        product = Products.objects.filter(tenant=request.tenant, product_name__iexact=product_name).first()
        if not product:
            product = Products.objects.filter(tenant=request.tenant, product_name__icontains=product_name).first()

        if not product:
            missing_products.append({'row': row_number, 'product': product_name})
            continue

        total_amount = purchase_price * quantity

        tax_rate = getattr(getattr(product, 'product_tax', None), 'tax_rate', 0)

        items.append({
            'product_id': product.id,
            'name': product.product_name,
            'packing': getattr(product, 'product_packing', ''),
            'conversion_factor': getattr(product, 'conversion_factor', 1),
            'batch_number': batch_number,
            'expiry_date': expiry_date if expiry_date else None,          # Can be None
            'quantity': quantity,
            'free_quantity': free_quantity,
            'total_units': (quantity + free_quantity) * getattr(product, 'conversion_factor', 1),
            'purchase_price': float(purchase_price),
            'tax_percentage': float(tax_rate),
            'tax_amount': float((purchase_price * quantity) * tax_rate / 100),
            'mrp': float(mrp),
            'sale_price': float(mrp),
            'total': float(total_amount)
        })

    return {
        'success': True,
        'invoice_number': invoice_number,
        'purchase_date': '2026-03-24',
        'supplier_name': None,
        'items': items,
        'missing_products': missing_products
    }