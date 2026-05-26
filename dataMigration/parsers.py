"""
dataMigration/parsers.py  — Debug Edition
==========================================
All parse functions now emit print() statements visible directly
in the Django terminal (manage.py runserver output).

Changes vs original:
  - Every public parser function prints entry, key decisions, and exit counts
  - parse_companies: prints sample accepted/rejected rows to debug column issues
  - parse_products_fast: prints per-10k progress + final junk/short stats
  - parse_suppliers_from_text: prints per-supplier found + any "no name" skips
  - parse_stock_batches: prints first few parsed batches for sanity check
  - Removed ThreadPoolExecutor (parse_products) — parse_products_fast is the
    correct path and is already used by workers.py; the threaded version is kept
    only for reference but prints a loud warning if called accidentally.
"""

import re
import csv
import io
import logging
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Debug helper — always goes to stdout (Django terminal)
# ─────────────────────────────────────────────────────────────
def _dbg(msg, *args):
    formatted = msg % args if args else msg
    print(f"[PARSER DEBUG] {formatted}", flush=True)
    logger.debug(formatted)


# ============================================================
# JUNK ROW FILTER
# ============================================================

def looks_like_packing(val):
    if not val:
        return False
    val = str(val).upper().strip()
    packing_patterns = [
        r'^\d+\s*ML$',
        r'^\d+\s*TAB$',
        r'^\d+\s*TABS$',
        r'^\d+\s*CAP$',
        r'^\d+\s*CAPS$',
        r'^\d+\s*PCS$',
        r'^\d+\s*VIAL$',
        r'^\d+\s*AMP$',
        r'^\d+\s*S$',
        r"^\d+\s*'S$",
    ]
    return any(re.match(p, val) for p in packing_patterns)


def clean_legacy_control_chars(text):
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)
    text = re.sub(r' +', ' ', text)
    return text


_JUNK_PATTERNS = re.compile(
    r'^(3DPM|MICRO\s*PRO|MICROPRO|PAGE\s*NO|PRINTED\s*ON|PRINT\s*DATE'
    r'|PRODUCT\s*TYPE\s*WISE|PRODUCTS\s*TYPEWISE|PRODUCT\s*WISE'
    r'|TULJAI\s*MED|BATCH\s*WISE|STOCK\s*REPORT|MASTER\s*LIST'
    r'|EXPIRY\s*WISE|COMPANY\s*MASTER|SUPPLIER\s*MASTER'
    r'|PHARMA\s*SOFTWARE|PAGE\s*:)',
    re.IGNORECASE
)

_COLUMN_HEADERS = {
    'PRODUCT NAME', 'PRODUCT', 'PROD NAME', 'PROD.NAME',
    'ITEM NAME', 'ITEM', 'NAME', 'DRUG NAME', 'DRUG',
    'P.NAME', 'P. NAME', 'PARTICULARS',
    'MFG', 'MFG.', 'COMPANY', 'MANUFACTURER',
    'PACK', 'PACKING', 'SCHEDULE', 'SCH', 'HSN',
    'PRODUCT 1',
}


def is_junk_report_row(row: list) -> bool:
    if not row:
        return True
    row_text = ' '.join(str(c).strip() for c in row if str(c).strip())
    if not row_text:
        return True
    if re.match(r'^[-=\.\*\s_#|+]+$', row_text):
        return True
    if _JUNK_PATTERNS.search(row_text):
        return True
    first_cell = str(row[0]).strip()
    if re.match(r'^\d{1,4}$', first_cell) and len(row) == 1:
        return True
    non_empty = [str(c).strip().upper() for c in row if str(c).strip()]
    if non_empty and all(cell in _COLUMN_HEADERS for cell in non_empty):
        return True
    if first_cell.upper() in _COLUMN_HEADERS:
        return True
    return False


def clean_value(val):
    if val is None:
        return ""
    return str(val).strip()


# ============================================================
# CSV / Text → rows
# ============================================================

def parse_csv_to_rows(content, drop_first_column=False):
    start_time = time.time()
    _dbg("parse_csv_to_rows: content_len=%d chars, drop_first_col=%s", len(content), drop_first_column)
    rows = []
    junk_count = 0
    csv_reader = csv.reader(io.StringIO(content))
    for row in csv_reader:
        cleaned = [str(col).strip() for col in row if str(col).strip()]
        if not cleaned:
            continue
        if is_junk_report_row(cleaned):
            junk_count += 1
            continue
        if drop_first_column and len(cleaned) > 1:
            cleaned = cleaned[1:]
        rows.append(cleaned)
    elapsed = time.time() - start_time
    _dbg("parse_csv_to_rows: produced %d rows in %.2fs (junk filtered: %d)", len(rows), elapsed, junk_count)
    if rows:
        _dbg("parse_csv_to_rows sample row[0]: %s", rows[0])
    if len(rows) == 0:
        _dbg("WARNING: parse_csv_to_rows returned 0 rows — check file encoding/format!")
    return rows


def parse_text_lines_to_rows(text_content, drop_first_column=False):
    start_time = time.time()
    _dbg("parse_text_lines_to_rows: content_len=%d chars, drop_first_col=%s", len(text_content), drop_first_column)
    lines = text_content.strip().split('\n')
    _dbg("parse_text_lines_to_rows: total raw lines=%d", len(lines))
    rows = []
    junk_count = 0
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        parts = re.split(r'\t| {2,}', line_str)
        cleaned_parts = [clean_value(x) for x in parts if x.strip()]
        if not cleaned_parts:
            continue
        if is_junk_report_row(cleaned_parts):
            junk_count += 1
            continue
        if drop_first_column and len(cleaned_parts) > 0:
            cleaned_parts = cleaned_parts[1:]
        rows.append(cleaned_parts)
    elapsed = time.time() - start_time
    _dbg("parse_text_lines_to_rows: produced %d rows in %.2fs (junk filtered: %d)", len(rows), elapsed, junk_count)
    if rows:
        _dbg("parse_text_lines_to_rows sample row[0]: %s", rows[0])
    if len(rows) == 0:
        _dbg("WARNING: parse_text_lines_to_rows returned 0 rows — check file encoding/format!")
    return rows


# ============================================================
# Date / Type helpers
# ============================================================

def parse_expiry_date(date_str):
    if not date_str:
        return None
    cleaned = re.sub(r'[\s//]+', '', date_str)
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(cleaned, fmt).date().strftime('%Y-%m-%d')
        except ValueError:
            pass
    for fmt in ('%m-%Y', '%m/%Y', '%b-%Y', '%Y-%m'):
        try:
            dt = datetime.strptime(cleaned, fmt)
            import calendar
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            return datetime(dt.year, dt.month, last_day).date().strftime('%Y-%m-%d')
        except ValueError:
            pass
    return None


def extract_conversion_and_type(packing_str, name_str=""):
    packing = clean_value(packing_str).upper()
    name = clean_value(name_str).upper()
    combined = f"{packing} {name}"
    conv_factor = 1
    if not packing:
        digits = re.findall(r'\d+', name)
        if digits:
            conv_factor = int(digits[0])
    digits = re.findall(r'\d+', packing)
    if digits:
        conv_factor = int(digits[0])
    if "TAB" in combined:
        prod_type = "TABLET"
    elif "CAP" in combined:
        prod_type = "CAPSULE"
    elif "DROP" in combined or "EYE" in combined or "EAR" in combined:
        prod_type = "DROP"
    elif "INJ" in combined or "AMP" in combined or "VIAL" in combined:
        prod_type = "INJECTION"
    elif "ML" in combined or "SYP" in combined or "LIQ" in combined or "SUSP" in combined:
        prod_type = "SYRUP"
    elif "CRE" in combined or "OIN" in combined or "GEL" in combined:
        prod_type = "CREAM"
    else:
        prod_type = "OTHER"
    return conv_factor, prod_type


# ============================================================
# 1. COMPANY MASTER
# ============================================================

def parse_companies(rows):

    import time
    start_time = time.time()

    print("=" * 80, flush=True)
    print(f"[COMPANY PARSER START] rows={len(rows)}", flush=True)

    companies = []

    skipped = 0

    for idx, r in enumerate(rows):

        try:

            if not r:
                continue

            r = [
                str(x).strip()
                for x in r
                if str(x).strip()
            ]

            if len(r) < 2:
                skipped += 1
                continue

            row_text = " ".join(r).upper()

            # =================================================
            # JUNK FILTER
            # =================================================

            junk_words = [
                'PRINTED ON',
                'PAGE NO',
                'MASTER LIST',
                'COMPANY NAME',
                'SHORT NAME',
                'CODE',
                '----',
                'TULJ',
                'COMP ANY'
            ]

            if any(j in row_text for j in junk_words):
                skipped += 1
                continue

            # =================================================
            # COMPANY CODE
            # =================================================

            company_code = ''

            if r[0].isdigit():

                company_code = r[0]

                company_name = r[1].strip().upper()

                short_name = (
                    r[2].strip().upper()
                    if len(r) > 2 else
                    company_name[:6]
                )

            else:

                # fallback
                company_name = r[0].strip().upper()

                short_name = (
                    r[1].strip().upper()
                    if len(r) > 1 else
                    company_name[:6]
                )

            if len(company_name) < 3:
                skipped += 1
                continue

            companies.append({
                'company_code': company_code,
                'company_name': company_name,
                'sht_name': short_name[:6],
            })

        except Exception as e:

            print(f"[COMPANY PARSER ERROR] row={idx} err={e}", flush=True)

    print(f"[COMPANY PARSER DONE] total={len(companies)}", flush=True)
    print(f"[COMPANY PARSER SKIPPED] {skipped}", flush=True)

    if companies:
        print(f"[SAMPLE] {companies[0]}", flush=True)

    print("=" * 80, flush=True)

    return companies


# ============================================================
# 2. SUPPLIER MASTER
# ============================================================

def clean_nested_labels(val):
    labels = [
        "Address", "Res.Add.Line1", "Res.Add.Line2", "Res.Add.Line3",
        "Res.Add.L", "Res.Add", "Add.L", "City", "Res.Phone",
        "Phone", "Mobile", "Fax", "Contact", "Purchase Type",
        "Purchase", "Discount %", "Cr.Days",
    ]
    for label in labels:
        val = re.sub(rf'{re.escape(label)}\s*:\s*', '', val, flags=re.IGNORECASE)
    val = re.sub(r'[\\\/]+$', '', val).strip()
    return val


def is_multiline_supplier_layout(rows):
    has_name = False
    has_indicators = False
    for r in rows:
        if not r:
            continue
        row_str = " ".join([str(x) for x in r])
        if re.search(r'Name\s*:', row_str, re.IGNORECASE):
            has_name = True
        if (re.search(r'Res\.Add', row_str, re.IGNORECASE) or
                re.search(r'Purchase\s+Type', row_str, re.IGNORECASE) or
                re.search(r'Discount\s*%', row_str, re.IGNORECASE) or
                re.search(r'Cr\.Days', row_str, re.IGNORECASE)):
            has_indicators = True
        if has_name and has_indicators:
            return True
    return False


def parse_supplier_block(block):
    supplier = {'name': '', 'phone': '', 'address': '', 'email': '', 'gst': '', 'dl': ''}
    address_parts = []
    for row in block:
        for cell in row:
            text = str(cell).strip()
            if not text:
                continue
            upper = text.upper()
            if upper.startswith('NAME'):
                match = re.search(r'Name\s*:\s*(?:\[[^\]]+\])?\s*(.*)', text, re.IGNORECASE)
                if match:
                    supplier['name'] = match.group(1).strip().upper()
                continue
            elif upper.startswith('ADDRESS'):
                addr = re.sub(r'Address\s*:', '', text, flags=re.IGNORECASE).strip()
                if addr:
                    address_parts.append(addr)
                continue
            elif upper.startswith('CITY'):
                city = re.sub(r'City\s*:', '', text, flags=re.IGNORECASE).strip()
                if city:
                    address_parts.append(city)
                continue
            elif upper.startswith('PHONE'):
                phone = re.sub(r'Phone\s*:', '', text, flags=re.IGNORECASE)
                phone = re.sub(r'[^\d]', '', phone)
                if phone:
                    supplier['phone'] = phone
                continue
            elif 'EMAIL' in upper:
                supplier['email'] = text.split(':')[-1].strip()
                continue
            elif 'GST' in upper:
                supplier['gst'] = text.split(':')[-1].strip().upper()
                continue
            elif 'DL' in upper:
                dl = text.split(':')[-1].strip()
                supplier['dl'] = dl.upper()
                continue
    supplier['address'] = ", ".join([x for x in address_parts if x])
    if not supplier['phone']:
        supplier['phone'] = '0000000000'
    return supplier


def parse_suppliers_from_rows_multiline(rows):
    start_time = time.time()
    _dbg("parse_suppliers_from_rows_multiline: starting with %d rows", len(rows))
    blocks = []
    current_block = []
    for r in rows:
        row_str = " ".join([str(x) for x in r]).strip()
        if not row_str:
            continue
        is_new_supplier = any(
            re.match(r'^Name\s*:', str(cell).strip(), re.IGNORECASE)
            for cell in r
        )
        if is_new_supplier:
            if current_block:
                blocks.append(current_block)
            current_block = [r]
        elif current_block:
            current_block.append(r)
    if current_block:
        blocks.append(current_block)

    _dbg("parse_suppliers_from_rows_multiline: found %d blocks", len(blocks))
    suppliers = []
    for block in blocks:
        if any(re.match(r'^Name\s*:', str(cell).strip(), re.IGNORECASE) for cell in block[0]):
            supplier = parse_supplier_block(block)
            if supplier['name']:
                suppliers.append(supplier)
            else:
                _dbg("  Supplier block had no name — skipped. Block row[0]: %s", block[0])

    elapsed = time.time() - start_time
    _dbg("parse_suppliers_from_rows_multiline: parsed %d suppliers in %.2fs", len(suppliers), elapsed)
    return suppliers


def parse_suppliers_from_text(text_content):
    start_time = time.time()
    _dbg("parse_suppliers_from_text: content_len=%d chars", len(text_content))
    suppliers = []
    current = None
    lines = text_content.splitlines()
    _dbg("parse_suppliers_from_text: total lines=%d", len(lines))

    for raw_line in lines:
        line = str(raw_line).strip()
        if not line:
            continue
        line = line.strip(',')
        upper = line.upper()

        if re.search(r'NAME\s*:', upper):
            if current and current.get('name'):
                suppliers.append(current)
                _dbg("  Supplier found: %s", current['name'])
            elif current and not current.get('name'):
                _dbg("  WARNING: supplier block had no name — skipped. Line was: %r", line)
            current = {'name': '', 'phone': '0000000000', 'address': '', 'email': '', 'gst': '', 'dl': ''}
            match = re.search(r'NAME\s*:\s*(?:\[[^\]]+\])?\s*(.*)', line, re.IGNORECASE)
            if match:
                current['name'] = match.group(1).replace(',', '').strip().upper()
            continue

        if re.search(r'ADDRESS\s*:', upper):
            if current:
                match = re.search(r'ADDRESS\s*:\s*(.*)', line, re.IGNORECASE)
                if match:
                    current['address'] = match.group(1).split('Res.Add')[0].replace('"', '').strip(' ,')
            continue

        if re.search(r'CITY\s*:', upper):
            if current:
                match = re.search(r'CITY\s*:\s*(.*)', line, re.IGNORECASE)
                if match:
                    city = match.group(1).split(',')[0].strip()
                    if city and city != '-':
                        current['address'] = (current['address'] + f", {city}") if current['address'] else city
            continue

        if re.search(r'PHONE\s*:', upper):
            if current:
                nums = re.findall(r'\d{10}', line)
                if nums:
                    current['phone'] = nums[0]
            continue

        if 'GST' in upper and current:
            nums = re.findall(r'[0-9A-Z]{15}', upper)
            if nums:
                current['gst'] = nums[0]

        if 'DL' in upper and current:
            dl = line.split(':')[-1].strip()
            if dl and dl != '-':
                current['dl'] = dl

    # flush last
    if current and current.get('name'):
        suppliers.append(current)
        _dbg("  Supplier found (last): %s", current['name'])

    elapsed = time.time() - start_time
    _dbg("parse_suppliers_from_text: parsed %d suppliers in %.2fs", len(suppliers), elapsed)
    if len(suppliers) == 0:
        _dbg("WARNING: parse_suppliers_from_text returned 0 suppliers!")
        _dbg("  Check: does your supplier file contain lines like 'Name : SUPPLIER NAME'?")
    return suppliers


def parse_suppliers_from_rows(rows):
    start_time = time.time()
    _dbg("parse_suppliers_from_rows: %d rows, detecting layout...", len(rows))
    if is_multiline_supplier_layout(rows):
        _dbg("parse_suppliers_from_rows: detected MULTILINE layout")
        result = parse_suppliers_from_rows_multiline(rows)
    else:
        _dbg("parse_suppliers_from_rows: detected TABULAR layout")
        suppliers = []
        for r in rows:
            if len(r) < 1:
                continue
            if r[0].upper() in ["NAME", "SUPPLIER", "SUPPLIER NAME", "CODE"]:
                continue
            supplier = {'name': '', 'code': '', 'phone': '', 'address': '', 'email': '', 'gst': '', 'dl': ''}
            if len(r) == 1:
                supplier['name'] = r[0].upper()
            elif len(r) == 2:
                supplier['name'] = r[0].upper()
                supplier['phone'] = re.sub(r'[^\d]+', '', r[1])
            elif len(r) == 3:
                supplier['name'] = r[0].upper()
                supplier['phone'] = re.sub(r'[^\d]+', '', r[1])
                supplier['address'] = r[2]
            else:
                supplier['name'] = r[0].upper()
                supplier['phone'] = re.sub(r'[^\d]+', '', r[1])
                supplier['address'] = r[2]
                supplier['email'] = r[3] if len(r) > 3 else ""
                supplier['gst'] = r[4].upper() if len(r) > 4 else ""
                supplier['dl'] = r[5].upper() if len(r) > 5 else ""
            if supplier['name']:
                suppliers.append(supplier)
        result = suppliers

    elapsed = time.time() - start_time
    _dbg("parse_suppliers_from_rows: parsed %d suppliers in %.2fs", len(result), elapsed)
    return result


# ============================================================
# 3. PRODUCT MASTER
# ============================================================

def parse_products_fast(rows):
    """
    Single-threaded product parser — the correct path for workers.
    The old ThreadPoolExecutor version (parse_products) is kept below
    for reference only; the GIL makes it useless for CPU-bound parsing.
    """
    start_time = time.time()
    _dbg("parse_products_fast: starting with %d rows", len(rows))
    if not rows:
        _dbg("WARNING: parse_products_fast received 0 rows!")
        return []

    products = []
    junk_skipped = 0
    short_skipped = 0
    packing_as_name_skipped = 0

    for idx, r in enumerate(rows):
        if idx % 10000 == 0 and idx > 0:
            _dbg("  parse_products_fast: %d / %d rows processed, %d accepted so far",
                 idx, len(rows), len(products))
        try:
            if len(r) < 1:
                continue
            if is_junk_report_row(r):
                junk_skipped += 1
                continue

            cleaned = [str(x).strip() for x in r if str(x).strip()]
            if not cleaned:
                continue

            product_name = ""
            packing = ""
            company = ""

            if len(cleaned) >= 2 and looks_like_packing(cleaned[1]):
                product_name = cleaned[0]
                packing = cleaned[1]
                if len(cleaned) > 2:
                    company = cleaned[2]
            elif looks_like_packing(cleaned[0]):
                packing_as_name_skipped += 1
                continue
            else:
                product_name = cleaned[0]
                if len(cleaned) > 1:
                    packing = cleaned[1]
                if len(cleaned) > 2:
                    company = cleaned[2]

            product_name = product_name.upper().strip()
            if len(product_name) < 3 or looks_like_packing(product_name):
                short_skipped += 1
                continue

            conv_factor, prod_type = extract_conversion_and_type(packing, product_name)
            products.append({
                'product_name': product_name,
                'product_packing': packing.upper(),
                'company_name': company.upper(),
                'hsn_code': '3004',
                'conversion_factor': conv_factor,
                'product_type': prod_type,
            })
        except Exception:
            continue

    elapsed = time.time() - start_time
    _dbg("parse_products_fast: DONE — accepted=%d, junk=%d, short=%d, packing_as_name=%d, time=%.2fs",
         len(products), junk_skipped, short_skipped, packing_as_name_skipped, elapsed)
    if products:
        _dbg("parse_products_fast sample: %s", products[0])
    if len(products) == 0:
        _dbg("WARNING: parse_products_fast produced 0 products!")
        _dbg("  Junk filter rejected %d rows. Short-name filter rejected %d rows.", junk_skipped, short_skipped)
        _dbg("  First 3 input rows were: %s", rows[:3])
    return products


def parse_product_master_text(text_content):
    start_time = time.time()
    _dbg("parse_product_master_text: content_len=%d chars", len(text_content))
    products = []
    lines = text_content.splitlines()
    _dbg("parse_product_master_text: total lines=%d", len(lines))
    skipped_junk = 0
    skipped_short = 0

    for idx, line in enumerate(lines):
        line = clean_legacy_control_chars(line).strip()
        if not line:
            continue
        upper_line = line.upper()
        if any(x in upper_line for x in [
            'PRINTED ON', 'PAGE NO', 'PRODUCT NAME', 'PACKING',
            'MFG', 'PRODUCT TYPE', '---', '===='
        ]):
            skipped_junk += 1
            continue
        if re.match(r'^[-=\.\*\s_#|+]+$', line):
            skipped_junk += 1
            continue
        parts = re.split(r'\s+', line)
        if len(parts) < 2:
            skipped_short += 1
            continue
        company = parts[-1].strip()
        packing = parts[-2].strip()
        product_name = " ".join(parts[:-2]).strip()
        if not product_name or looks_like_packing(product_name) or len(product_name) < 3:
            skipped_short += 1
            continue
        product_name = re.sub(r'^\d+\s+', '', product_name)
        conv_factor, prod_type = extract_conversion_and_type(packing, product_name)
        products.append({
            'product_name': product_name.upper(),
            'product_packing': packing.upper(),
            'company_name': company.upper(),
            'hsn_code': '3004',
            'conversion_factor': conv_factor,
            'product_type': prod_type,
        })

    elapsed = time.time() - start_time
    _dbg("parse_product_master_text: accepted=%d, junk=%d, short=%d, time=%.2fs",
         len(products), skipped_junk, skipped_short, elapsed)
    if products:
        _dbg("parse_product_master_text sample: %s", products[0])
    if len(products) == 0:
        _dbg("WARNING: parse_product_master_text produced 0 products!")
        _dbg("  Expected format per line: PRODUCT_NAME PACKING COMPANY")
    return products


# ── Threaded version kept for reference — NOT used by workers.py ─────────────
MAX_WORKERS = 10
CHUNK_SIZE = 5000


def process_product_chunk(chunk_rows):
    chunk_products = []
    for r in chunk_rows:
        try:
            if len(r) < 1 or is_junk_report_row(r):
                continue
            cleaned = [str(x).strip() for x in r if str(x).strip()]
            if not cleaned:
                continue
            product_name = packing = company = ""
            if len(cleaned) >= 2 and looks_like_packing(cleaned[1]):
                product_name, packing = cleaned[0], cleaned[1]
                if len(cleaned) > 2:
                    company = cleaned[2]
            elif looks_like_packing(cleaned[0]):
                continue
            else:
                product_name = cleaned[0]
                if len(cleaned) > 1:
                    packing = cleaned[1]
                if len(cleaned) > 2:
                    company = cleaned[2]
            product_name = product_name.upper().strip()
            if len(product_name) < 3 or looks_like_packing(product_name):
                continue
            conv_factor, prod_type = extract_conversion_and_type(packing, product_name)
            chunk_products.append({
                'product_name': product_name,
                'product_packing': packing,
                'company_name': company.upper(),
                'hsn_code': '3004',
                'conversion_factor': conv_factor,
                'product_type': prod_type,
            })
        except Exception as e:
            logger.warning("Row Error in process_product_chunk: %s", e)
    return chunk_products


def chunkify(data, chunk_size):
    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]


def parse_products(rows):
    """
    DEPRECATED — ThreadPoolExecutor gives no speedup for CPU-bound
    Python code due to the GIL. Use parse_products_fast() instead.
    This function is kept only so old imports don't break.
    """
    _dbg("WARNING: parse_products (threaded) called — use parse_products_fast() instead!")
    print("[PARSER WARNING] parse_products (ThreadPoolExecutor) called. Switch to parse_products_fast()!", flush=True)
    return parse_products_fast(rows)


# ============================================================
# 4. STOCK & BATCHES
# ============================================================

def parse_stock_batches(rows):

    start_time = time.time()

    _dbg(
        "parse_stock_batches: starting with %d rows",
        len(rows)
    )

    if not rows:

        _dbg(
            "WARNING: parse_stock_batches received 0 rows!"
        )

        return []

    batches = []

    current_product_code = ""

    current_product_name = ""

    current_company = ""

    current_type = "TABLET"

    skipped_no_batch = 0

    skipped_too_short = 0

    skipped_junk = 0

    for idx, r in enumerate(rows):

        try:

            # =====================================================
            # NORMALIZE ROW
            # =====================================================

            r = [
                str(x).strip()
                for x in r
                if str(x).strip()
            ]

            if idx < 5:

                _dbg(
                    "NORMALIZED STOCK ROW %d = %s",
                    idx,
                    r
                )

            if len(r) < 2:

                skipped_too_short += 1

                continue

            row_text = " ".join(r).upper()

            # =====================================================
            # SKIP JUNK ROWS
            # =====================================================

            junk_words = [
                "PRODUCT NAME",
                "P.CODE",
                "TULJAI MEDICALS",
                "PRODUCTS TYPEWISE",
                "CLOSE",
                "PAGE",
                "PROD.TYPE",
                "-----",
            ]

            if any(x in row_text for x in junk_words):

                skipped_junk += 1

                # Detect product type

                type_match = re.search(
                    r'PROD\.TYPE\s*:\s*\[?\]?([^\[\]\:]+)',
                    row_text,
                    re.IGNORECASE
                )

                if type_match:

                    current_type = (
                        type_match
                        .group(1)
                        .strip()
                        .upper()
                    )

                    _dbg(
                        "parse_stock_batches: product type changed to '%s'",
                        current_type
                    )

                continue

            # =====================================================
            # PAD ROW
            # =====================================================

            row_cells = r + [""] * (7 - len(r))

            # =====================================================
            # FIND EXPIRY COLUMN
            # =====================================================

            expiry_idx = -1

            for col_idx in range(len(row_cells)):

                if parse_expiry_date(
                    row_cells[col_idx]
                ) is not None:

                    expiry_idx = col_idx

                    break

            if expiry_idx == -1:

                skipped_no_batch += 1

                continue

            # =====================================================
            # DETECT SHIFTED ROW
            # =====================================================

            if expiry_idx == 2:

                is_shifted = True

            elif expiry_idx == 3:

                is_shifted = False

            else:

                first_col = row_cells[0].strip()

                is_shifted = (
                    first_col
                    .replace('.', '', 1)
                    .isdigit()
                    and expiry_idx == 2
                )

            # =====================================================
            # SHIFTED / CONTINUATION ROW
            # =====================================================

            if is_shifted:

                mrp_str = row_cells[0]

                batch_no = row_cells[1]

                expiry_str = row_cells[2]

                qty_str = row_cells[3]

                company = (
                    row_cells[-1]
                    or current_company
                )

                p_code = current_product_code

                p_name = current_product_name

            # =====================================================
            # NEW PRODUCT ROW
            # =====================================================

            else:

                col_0 = row_cells[0].strip()

                code_name_match = re.match(
                    r'^(\d+)\s+(.*)',
                    col_0
                )

                if code_name_match:

                    p_code = (
                        code_name_match
                        .group(1)
                    )

                    p_name = (
                        code_name_match
                        .group(2)
                        .strip()
                        .upper()
                    )

                else:

                    p_name = col_0.upper()

                    p_code = ""

                mrp_str = row_cells[1]

                batch_no = row_cells[2]

                expiry_str = row_cells[3]

                qty_str = row_cells[4]

                company = (
                    row_cells[-1]
                    if row_cells else ""
                )

                current_product_code = p_code

                current_product_name = p_name

                current_company = (
                    company
                    or current_company
                )

            # =====================================================
            # CLEAN COMPANY
            # =====================================================

            company = (
                company.strip()
                if company else ""
            )

            if company:

                m = re.match(
                    r'^\d+\s+(.*)',
                    company
                )

                if m:

                    company = (
                        m.group(1)
                        .strip()
                    )

                company = re.sub(
                    r'\d+$',
                    '',
                    company
                ).strip()

            # =====================================================
            # PARSE MRP
            # =====================================================

            try:

                mrp = float(
                    re.sub(
                        r'[^\d\.]+',
                        '',
                        mrp_str
                    )
                ) if mrp_str else 0.0

            except ValueError:

                mrp = 0.0

            # =====================================================
            # PARSE QTY
            # =====================================================

            try:

                qty = int(
                    re.sub(
                        r'[^\d]+',
                        '',
                        qty_str
                    )
                ) if qty_str else 0

            except ValueError:

                qty = 0

            # =====================================================
            # PARSE EXPIRY
            # =====================================================

            expiry = parse_expiry_date(
                expiry_str
            )

            # =====================================================
            # VALIDATE
            # =====================================================

            if not p_name:

                skipped_no_batch += 1

                continue

            if not batch_no:

                skipped_no_batch += 1

                continue

            # =====================================================
            # CONVERSION + TYPE
            # =====================================================

            conv_factor, derived_type = (
                extract_conversion_and_type(
                    p_name,
                    p_name
                )
            )

            # =====================================================
            # FINAL APPEND
            # =====================================================

            batches.append({

                'product_code': p_code,

                'product_name': p_name,

                'product_type': (
                    current_type
                    if current_type != "TABLET"
                    else derived_type
                ),

                'conversion_factor': conv_factor,

                'mrp': mrp,

                'batch_number': (
                    batch_no
                    .upper()
                    .strip()
                ),

                'expiry_date': expiry,

                'quantity': qty,

                'company_name': (
                    company.strip().upper()
                    if company else
                    current_company.strip().upper()
                ),
            })

        except Exception as e:

            _dbg(
                "parse_stock_batches ERROR row=%d err=%s row=%s",
                idx,
                e,
                r
            )

    elapsed = time.time() - start_time

    _dbg(
        "parse_stock_batches: accepted=%d, skipped_no_batch=%d, skipped_too_short=%d, skipped_junk=%d, time=%.2fs",
        len(batches),
        skipped_no_batch,
        skipped_too_short,
        skipped_junk,
        elapsed
    )

    if batches:

        _dbg(
            "parse_stock_batches sample batch[0]: %s",
            batches[0]
        )

    if len(batches) == 0:

        _dbg(
            "WARNING: parse_stock_batches produced 0 batches!"
        )

        _dbg(
            "First 3 input rows: %s",
            rows[:3]
        )

    return batches