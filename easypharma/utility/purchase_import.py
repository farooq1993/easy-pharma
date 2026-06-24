import re
from decimal import Decimal
import csv
import io
from easypharma.models.Items import Products
from easypharma.models.purchase_invoice import PurchaseInvoice


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
    """
    Handles multiple expiry formats:
      - DDMMYYYY        → e.g. 01062026
      - DD-MM-YYYY      → e.g. 01-06-2026
      - DD/MM/YYYY      → e.g. 01/06/2026
      - DDMMYYYY (8-digit MicroPro style) → e.g. 31102028
    """
    if not value:
        return None
    text = str(value).strip()

    # 1. Pure 8-digit DDMMYYYY
    if len(text) == 8 and text.isdigit():
        day = text[0:2]
        month = text[2:4]
        year = text[4:8]
        if 1 <= int(month) <= 12:
            return f'{year}-{month}-{day}'

    # 2. DD-MM-YYYY or DD/MM/YYYY or DD.MM.YYYY
    text = re.sub(r'[/\.]', '-', text)
    if re.match(r'^\d{1,2}-\d{1,2}-\d{4}$', text):
        parts = text.split('-')
        day, month, year = parts[0], parts[1], parts[2]
        if len(year) == 4 and 1 <= int(month) <= 12:
            return f'{year}-{month.zfill(2)}-{day.zfill(2)}'

    return None


# ====================== FORMAT DETECTION ======================

def detect_csv_format(rows):
    """
    Returns:
      'marg'    → BAGDI / Marg Software format
      'micropro' → MicroPro format (H/T row structure)
      'unknown'
    """
    for row in rows[:5]:
        if row and str(row[0]).strip().upper() == 'H':
            return 'micropro'

    for row in rows:
        for cell in row:
            if str(cell).strip() in ('Particulars', 'Batchno', 'Qty.'):
                return 'marg'

    return 'unknown'


# ====================== MARG FORMAT ======================

def find_marg_header_row(rows):
    """Find the row index that has column headers like 'Particulars', 'Batchno', etc."""
    for idx, row in enumerate(rows):
        row_values = [str(c).strip() for c in row]
        if 'Particulars' in row_values and 'Batchno' in row_values:
            return idx
    return None


def parse_marg_format(rows, request):
    """
    Marg Software CSV:
      Row 15 (0-indexed): HSN Code | Particulars | Packing | Company | Batchno | Expiry | MFG | M.R.P. | Qty. | Free | Rate | SGST% | CGST% | Amount | Disc% | Barcode
      Indices:              0          1             2         3         4         5        6     7        8      9     10     11      12      13       14      15
    """
    header_idx = find_marg_header_row(rows)
    if header_idx is None:
        return None, "Marg format: Header row with 'Particulars' not found."

    headers = [str(c).strip() for c in rows[header_idx]]

    def col(name):
        try:
            return headers.index(name)
        except ValueError:
            return None

    idx_product  = col('Particulars')
    idx_batch    = col('Batchno')
    idx_expiry   = col('Expiry')
    idx_qty      = col('Qty.')
    idx_free     = col('Free')
    idx_rate     = col('Rate')
    idx_mrp      = col('M.R.P.')

    if idx_product is None:
        return None, "Marg format: 'Particulars' column not found."

    # Extract invoice number from header area
    invoice_number = None
    for row in rows[:header_idx]:
        for cell in row:
            m = re.search(r'INV[-_]?\d+', str(cell), re.IGNORECASE)
            if m:
                invoice_number = m.group(0).strip()
                break
        if invoice_number:
            break

    items = []
    missing_products = []

    for row_number, row in enumerate(rows[header_idx + 1:], start=header_idx + 2):
        if len(row) <= max(filter(None, [idx_product, idx_rate, idx_mrp])):
            continue

        product_name = str(row[idx_product]).strip() if idx_product is not None else ''
        if not product_name or len(product_name) < 3:
            continue
        # Skip footer/total rows
        if re.match(r'^(total|grand|sub.?total)', product_name, re.IGNORECASE):
            continue

        batch_number  = str(row[idx_batch]).strip()  if idx_batch  is not None and len(row) > idx_batch  else ''
        expiry_text   = str(row[idx_expiry]).strip() if idx_expiry is not None and len(row) > idx_expiry else ''
        quantity      = parse_integer_value(row[idx_qty]  if idx_qty  is not None and len(row) > idx_qty  else 0)
        free_quantity = parse_integer_value(row[idx_free] if idx_free is not None and len(row) > idx_free else 0)
        purchase_price = parse_decimal_value(row[idx_rate] if idx_rate is not None and len(row) > idx_rate else 0)
        mrp            = parse_decimal_value(row[idx_mrp]  if idx_mrp  is not None and len(row) > idx_mrp  else 0)
        expiry_date    = parse_expiry(expiry_text)

        product = (
            Products.objects.filter(tenant=request.tenant, product_name__iexact=product_name).first()
            or Products.objects.filter(tenant=request.tenant, product_name__icontains=product_name).first()
        )

        if not product:
            missing_products.append({'row': row_number, 'product': product_name})
            continue

        tax_rate    = getattr(getattr(product, 'product_tax', None), 'tax_rate', 0)
        total_amount = purchase_price * quantity

        items.append({
            'product_id':        product.id,
            'name':              product.product_name,
            'packing':           getattr(product, 'product_packing', ''),
            'conversion_factor': getattr(product, 'conversion_factor', 1),
            'batch_number':      batch_number,
            'expiry_date':       expiry_date,
            'quantity':          quantity,
            'free_quantity':     free_quantity,
            'total_units':       (quantity + free_quantity) * getattr(product, 'conversion_factor', 1),
            'purchase_price':    float(purchase_price),
            'tax_percentage':    float(tax_rate),
            'tax_amount':        float((purchase_price * quantity) * tax_rate / 100),
            'mrp':               float(mrp),
            'sale_price':        float(mrp),
            'total':             float(total_amount),
        })

    return {
        'invoice_number': invoice_number,
        'items':          items,
        'missing_products': missing_products,
    }, None


# ====================== MICROPRO FORMAT ======================

def parse_micropro_format(rows, request):
    """
    MicroPro CSV — pipe-delimited (no actual pipe; fixed column positions):
      H row  → col[2]=InvoiceNo, col[3]=InvoiceDate (DDMMYYYY)
      T rows → col[4]=ItemCode, col[5]=ProductName, col[6]=Packing, col[7]=Company,
                col[8]=BatchNo,  col[9]=Expiry(DDMMYYYY),
                col[11]=PurchaseRate, col[12]=MRP,
                col[16]=Qty,     col[17]=FreeQty
    MicroPro column indices (0-based):
      0:RecType  1:-  2:InvNo  3:InvDate  4:ItemCode  5:ProductName  6:Packing  7:Company
      8:BatchNo  9:Expiry  10:MFGDate  11:PurRate  12:PurRate2  13:MRP
      14:Disc%  15:-  16:Qty  17:FreeQty  18:TotalQty  19:Disc  20:-  21:Amount
      22:GST%  23:GSTAmt  24:GST%2  25:GSTAmt2  ...  30:HSN
    """
    invoice_number = None
    invoice_date   = None
    items = []
    missing_products = []

    for row_number, row in enumerate(rows, start=1):
        if not row:
            continue
        rec_type = str(row[0]).strip().upper()

        # ── Header row ──
        if rec_type == 'H':
            if len(row) > 2:
                inv_raw = str(row[2]).strip()
                if inv_raw:
                    invoice_number = inv_raw
            if len(row) > 3:
                date_raw = str(row[3]).strip()
                # DDMMYYYY format
                if len(date_raw) == 8 and date_raw.isdigit():
                    invoice_date = f'{date_raw[4:8]}-{date_raw[2:4]}-{date_raw[0:2]}'
            continue

        # ── Transaction / item row ──
        if rec_type == 'T':
            if len(row) < 17:
                continue

            product_name  = str(row[5]).strip()
            if not product_name or len(product_name) < 3:
                continue

            batch_number   = str(row[8]).strip()  if len(row) > 8  else ''
            expiry_text    = str(row[9]).strip()   if len(row) > 9  else ''
            # MicroPro T-row verified column mapping:
            # col[10]=PurRate, col[12]=MRP, col[15]=Qty, col[16]=FreeQty
            purchase_price = parse_decimal_value(row[10] if len(row) > 10 else 0)
            mrp            = parse_decimal_value(row[12] if len(row) > 12 else 0)
            quantity       = parse_integer_value(row[15] if len(row) > 15 else 0)
            free_quantity  = parse_integer_value(row[16] if len(row) > 16 else 0)
            expiry_date    = parse_expiry(expiry_text)

            product = (
                Products.objects.filter(tenant=request.tenant, product_name__iexact=product_name).first()
                or Products.objects.filter(tenant=request.tenant, product_name__icontains=product_name).first()
            )

            if not product:
                missing_products.append({'row': row_number, 'product': product_name})
                continue

            tax_rate     = getattr(getattr(product, 'product_tax', None), 'tax_rate', 0)
            total_amount = purchase_price * quantity

            items.append({
                'product_id':        product.id,
                'name':              product.product_name,
                'packing':           getattr(product, 'product_packing', ''),
                'conversion_factor': getattr(product, 'conversion_factor', 1),
                'batch_number':      batch_number,
                'expiry_date':       expiry_date,
                'quantity':          quantity,
                'free_quantity':     free_quantity,
                'total_units':       (quantity + free_quantity) * getattr(product, 'conversion_factor', 1),
                'purchase_price':    float(purchase_price),
                'tax_percentage':    float(tax_rate),
                'tax_amount':        float((purchase_price * quantity) * tax_rate / 100),
                'mrp':               float(mrp),
                'sale_price':        float(mrp),
                'total':             float(total_amount),
            })

    return {
        'invoice_number': invoice_number,
        'purchase_date':  invoice_date,
        'items':          items,
        'missing_products': missing_products,
    }, None


# ====================== MAIN PROCESSOR ======================

def process_csv_file(csv_file, request):
    # ── Read file ──
    try:
        file_data = csv_file.read().decode('utf-8-sig')
    except UnicodeDecodeError:
        file_data = csv_file.read().decode('latin-1', errors='ignore')

    reader = csv.reader(io.StringIO(file_data))
    rows = [r for r in reader if any(str(cell).strip() for cell in r)]

    if not rows:
        return {'success': False, 'error': 'CSV file is empty.'}

    # ── Detect format ──
    fmt = detect_csv_format(rows)

    if fmt == 'marg':
        result, error = parse_marg_format(rows, request)
    elif fmt == 'micropro':
        result, error = parse_micropro_format(rows, request)
    else:
        return {'success': False, 'error': 'Unknown CSV format. Only Marg and MicroPro formats are supported.'}

    if error:
        return {'success': False, 'error': error}

    # ── Duplicate invoice check ──
    invoice_number = result.get('invoice_number')
    if invoice_number and PurchaseInvoice.objects.filter(
        tenant=request.tenant, invoice_number=invoice_number
    ).exists():
        return {'success': False, 'error': f"Invoice {invoice_number} is already imported."}

    if not result['items']:
        msg = 'No valid products found in CSV.'
        if result['missing_products']:
            names = ', '.join(p['product'] for p in result['missing_products'][:5])
            msg += f' Missing products: {names}'
        return {'success': False, 'error': msg}

    return {
        'success':          True,
        'format':           fmt,
        'invoice_number':   invoice_number,
        'purchase_date':    result.get('purchase_date'),
        'supplier_name':    None,
        'items':            result['items'],
        'missing_products': result['missing_products'],
    }