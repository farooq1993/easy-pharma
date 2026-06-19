import re
from decimal import Decimal
import csv
import io
from easypharma.models.Items import Products

# ====================== ALL HELPERS (for backward compatibility) ======================

def normalize_column_name(value):
    if value is None:
        return ''
    val = str(value).strip().lower()
    val = re.sub(r'[^a-z0-9]+', ' ', val)
    return re.sub(r'\s+', ' ', val).strip()


def find_column(headers, names):
    for idx, header in enumerate(headers):
        h = normalize_column_name(header)
        for name in names:
            if name in h:
                return idx
    return None


def looks_like_date(value):
    if not value:
        return False
    text = str(value).strip().replace('/', '-').replace('.', '-')
    patterns = [r'^\d{1,2}-\d{1,2}-\d{2,4}$', r'^\d{4}-\d{1,2}$', r'^\d{2}/\d{4}$', r'^\d{6,8}$']
    return any(re.match(p, text) for p in patterns)


def looks_like_integer(value):
    if not value:
        return False
    text = str(value).strip().split()[0].replace(',', '')
    return re.fullmatch(r'[-+]?\d+', text) is not None


def looks_like_decimal(value):
    if not value:
        return False
    text = str(value).strip().split()[0].replace(',', '')
    return re.fullmatch(r'[-+]?\d*\.?\d+', text) is not None


def is_likely_product_name(value):
    if not value:
        return False
    text = str(value).strip()
    if len(text) < 4 or looks_like_date(text) or looks_like_decimal(text) or looks_like_integer(text):
        return False
    alpha = sum(1 for c in text if c.isalpha())
    return alpha >= 4 and (' ' in text or len(text.split()) >= 2)


def is_likely_batch(value):
    if not value:
        return False
    text = str(value).strip()
    if not text or len(text) < 3 or len(text) > 20 or ' ' in text:
        return False
    return any(c.isalpha() for c in text) and any(c.isdigit() for c in text)


# ====================== PARSERS ======================

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
        return ''
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():   # DDMMYYYY → YYYY-MM-DD
        day = text[0:2]
        month = text[2:4]
        year = text[4:8]
        if 1 <= int(month) <= 12:
            return f'{year}-{month}-{day}'
    return ''
    # Fallback
    text = re.sub(r'[/\.]', '-', text)
    parts = [p for p in text.split('-') if p]
    if len(parts) == 3:
        year, month = parts[-1], parts[1] if len(parts[1]) == 2 else parts[0]
    elif len(parts) == 2:
        if len(parts[0]) == 4:
            year, month = parts[0], parts[1]
        else:
            year, month = parts[1], parts[0]
    else:
        return ''
    if len(month) == 1: month = '0' + month
    if len(year) == 2: year = '20' + year
    if year.isdigit() and month.isdigit() and 1 <= int(month) <= 12:
        return f'{year}-{month}'
    return ''


# ====================== TUNED INFERENCE FOR YOUR CSV ======================

def infer_purchase_columns(rows):
    """Hard-coded indices based on your exact CSV structure"""
    return {
        'product_idx': 5,      # Medicine Name
        'batch_idx': 8,        # Batch No
        'expiry_idx': 9,       # Expiry (DDMMYYYY)
        'qty_idx': 15,         # Quantity
        'free_idx': None,
        'purchase_price_idx': 12,  # Purchase Rate (before discount)
        'mrp_idx': 10,         # MRP
        'discount_idx': 18,    # Discount column (if needed)
        'sale_price_idx': None,
        'total_idx': None,
        'invoice_idx': None,
        'date_idx': None
    }


# ====================== GUESS FUNCTIONS ======================

def guess_invoice_number(rows):
    for row in rows[:5]:
        for cell in row:
            if re.search(r'INV\d+', str(cell)):
                return str(cell).strip()
    return None


def guess_purchase_date(rows):
    return "2026-03-24"  # From filename

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

    # Get Invoice Number
    for row in rows[:3]:
        for cell in row:
            if re.search(r'INV\d+', str(cell)):
                invoice_number = str(cell).strip()
                break
        if invoice_number:
            break

    for row_number, row in enumerate(rows, start=1):
        if len(row) < 16 or row[0] != 'T':
            continue

        product_name = str(row[inferred['product_idx']]).strip()
        if not product_name:
            continue

        batch_number = str(row[inferred['batch_idx']]).strip() if len(row) > inferred['batch_idx'] else ''
        expiry_text = str(row[inferred['expiry_idx']]).strip() if len(row) > inferred['expiry_idx'] else ''
        quantity = parse_integer_value(row[inferred['qty_idx']] if len(row) > inferred['qty_idx'] else 0)
        purchase_price = parse_decimal_value(row[inferred['purchase_price_idx']] if len(row) > inferred['purchase_price_idx'] else 0)
        mrp = parse_decimal_value(row[inferred['mrp_idx']] if len(row) > inferred['mrp_idx'] else 0)

        # Handle Discount (if present)
        discount = parse_decimal_value(row[inferred.get('discount_idx')] if len(row) > inferred.get('discount_idx', 0) else 0, Decimal('0'))

        expiry_date = parse_expiry(expiry_text)

        product = Products.objects.filter(tenant=request.tenant, product_name__iexact=product_name).first()
        if not product:
            product = Products.objects.filter(tenant=request.tenant, product_name__icontains=product_name).first()

        if not product:
            missing_products.append({'row': row_number, 'product': product_name})
            continue

        # Final purchase price after discount (if discount exists)
        final_purchase_price = purchase_price - discount if discount > 0 else purchase_price

        total_amount = final_purchase_price * quantity

        items.append({
            'product_id': product.id,
            'name': product.product_name,
            'packing': getattr(product, 'product_packing', ''),
            'conversion_factor': getattr(product, 'conversion_factor', 1),
            'batch_number': batch_number,
            'expiry_date': expiry_date,
            'quantity': quantity,
            'free_quantity': 0,
            'total_units': quantity * getattr(product, 'conversion_factor', 1),
            'purchase_price': float(final_purchase_price),
            'tax_percentage': float(getattr(getattr(product, 'product_tax', None), 'tax_rate', 0)),
            'tax_amount': float((final_purchase_price * quantity) * (getattr(getattr(product, 'product_tax', None), 'tax_rate', 0)) / 100),
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