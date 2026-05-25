import re
import csv
import io
from datetime import datetime


# ============================================================
# JUNK ROW FILTER — strips legacy Micropro/3DPM print headers
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
        r'^\d+\s*\'S$',
    ]

    return any(re.match(p, val) for p in packing_patterns)

def clean_legacy_control_chars(text):

    # remove ESC/P printer control chars
    text = re.sub(r'[\x00-\x1F\x7F-\x9F]', '', text)

    # remove weird repeated spaces
    text = re.sub(r' +', ' ', text)

    return text

def parse_product_master_text(text_content):

    products = []

    for idx, line in enumerate(lines):

        line = clean_legacy_control_chars(line)

        original_line = str(line)

        line = original_line.strip()

        if not line:
            continue

        upper_line = line.upper()

        # -----------------------------------
        # SKIP JUNK
        # -----------------------------------

        if any(x in upper_line for x in [
            'PRINTED ON',
            'PAGE NO',
            'PRODUCT NAME',
            'PACKING',
            'MFG',
            'PRODUCT TYPE',
            '---',
            '===='
        ]):
            continue

        # separator
        if re.match(r'^[-=\.\*\s_#|+]+$', line):
            continue

        # -----------------------------------
        # TOKENIZE
        # -----------------------------------

        parts = re.split(r'\s+', line)

        if len(parts) < 2:
            continue

        # -----------------------------------
        # LAST TOKEN = COMPANY
        # SECOND LAST = PACKING
        # REMAINING = PRODUCT
        # -----------------------------------

        company = parts[-1].strip()

        packing = parts[-2].strip()

        product_name = " ".join(parts[:-2]).strip()

        # -----------------------------------
        # SAFETY CHECKS
        # -----------------------------------

        if not product_name:
            continue

        if looks_like_packing(product_name):
            continue

        if len(product_name) < 3:
            continue

        # remove serial number
        product_name = re.sub(
            r'^\d+\s+',
            '',
            product_name
        )

        conv_factor, prod_type = extract_conversion_and_type(
            packing,
            product_name
        )

        products.append({

            'product_name': product_name.upper(),

            'product_packing': packing.upper(),

            'company_name': company.upper(),

            'hsn_code': '3004',

            'conversion_factor': conv_factor,

            'product_type': prod_type

        })
    print("==== Parsed products from text content =====", products)
    return products

# Patterns that ALWAYS indicate a report metadata / separator row
_JUNK_PATTERNS = re.compile(
    r'^(3DPM|MICRO\s*PRO|MICROPRO|PAGE\s*NO|PRINTED\s*ON|PRINT\s*DATE'
    r'|PRODUCT\s*TYPE\s*WISE|PRODUCTS\s*TYPEWISE|PRODUCT\s*WISE'
    r'|TULJAI\s*MED|BATCH\s*WISE|STOCK\s*REPORT|MASTER\s*LIST'
    r'|EXPIRY\s*WISE|COMPANY\s*MASTER|SUPPLIER\s*MASTER'
    r'|PHARMA\s*SOFTWARE|PAGE\s*:)'
    , re.IGNORECASE
)

# Column header keywords that appear on every page break
_COLUMN_HEADERS = {
    'PRODUCT NAME', 'PRODUCT', 'PROD NAME', 'PROD.NAME',
    'ITEM NAME', 'ITEM', 'NAME', 'DRUG NAME', 'DRUG',
    'P.NAME', 'P. NAME', 'PARTICULARS',
    'MFG', 'MFG.', 'COMPANY', 'MANUFACTURER',
    'PACK', 'PACKING', 'SCHEDULE', 'SCH', 'HSN',
    'PRODUCT 1',  # specific 3DPM artifact
}


def is_junk_report_row(row: list) -> bool:
    """
    Returns True when a parsed row represents report metadata,
    a page separator, a column-header repetition, or a print marker
    that should NEVER be imported as a real data record.

    Handles legacy Micropro, 3DPM, and similar printed-report CSVs.
    """
    if not row:
        return True

    # -- join all cells for whole-row checks --
    row_text = ' '.join(str(c).strip() for c in row if str(c).strip())

    if not row_text:
        return True

    # Separator / divider lines (dashes, equals, dots, stars …)
    if re.match(r'^[-=\.\*\s_#|+]+$', row_text):
        return True

    # Report-level metadata keywords (page numbers, print dates …)
    if _JUNK_PATTERNS.search(row_text):
        return True

    # Pure numeric rows with very few chars (page numbers, SR no footers)
    first_cell = str(row[0]).strip()
    if re.match(r'^\d{1,4}$', first_cell) and len(row) == 1:
        return True

    # Column-header repetitions (appear on every page of printed reports)
    # A row is a header row if ALL of its non-empty cells match known header keywords
    non_empty = [str(c).strip().upper() for c in row if str(c).strip()]
    if non_empty and all(cell in _COLUMN_HEADERS for cell in non_empty):
        return True

    # First cell is exactly a known column header keyword
    if first_cell.upper() in _COLUMN_HEADERS:
        return True

    return False

def clean_value(val):
    if val is None:
        return ""
    return str(val).strip()

import csv
import io


def parse_csv_to_rows(
    content,
    drop_first_column=False
):

    rows = []

    csv_reader = csv.reader(
        io.StringIO(content)
    )

    for row in csv_reader:

        # ------------------------------------
        # CLEAN EMPTY CELLS
        # ------------------------------------

        cleaned = [

            str(col).strip()

            for col in row

            if str(col).strip()

        ]

        if not cleaned:
            continue

        # ------------------------------------
        # SKIP LEGACY REPORT JUNK ROWS
        # ------------------------------------

        if is_junk_report_row(cleaned):
            continue

        # ------------------------------------
        # OPTIONAL COLUMN DROP
        # ------------------------------------

        if (
            drop_first_column
            and len(cleaned) > 1
        ):

            cleaned = cleaned[1:]

        rows.append(cleaned)

    return rows

# def parse_csv_to_rows(file_content_str, drop_first_column=False):
#     """
#     Parses a CSV string content into a clean list of lists (rows).
#     Drops the first column if drop_first_column is True.
#     """
#     f = io.StringIO(file_content_str.strip())
#     reader = csv.reader(f)
#     rows = []
#     for r in reader:
#         if not r:
#             continue
#         cleaned_row = [clean_value(x) for x in r]
#         if drop_first_column and len(cleaned_row) > 0:
#             cleaned_row = cleaned_row[1:]
#         rows.append(cleaned_row)
#     return rows

def parse_text_lines_to_rows(text_content, drop_first_column=False):
    """
    Parses raw pasted text into lines, tokenizing them by multiple spaces or tabs.
    Ignores divider lines like dashes or equal signs.
    """
    lines = text_content.strip().split('\n')
    rows = []
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue

        # Split by tabs or double spaces or commas
        #parts = re.split(r',|\t| {2,}', line_str)
        parts = re.split(r'\t| {2,}', line_str)
        cleaned_parts = [clean_value(x) for x in parts if x.strip()]

        if not cleaned_parts:
            continue

        # Skip legacy report junk rows (page headers, dividers, column-header repeats)
        if is_junk_report_row(cleaned_parts):
            continue

        if drop_first_column and len(cleaned_parts) > 0:
            cleaned_parts = cleaned_parts[1:]

        rows.append(cleaned_parts)
    return rows

def parse_expiry_date(date_str):
    """
    Converts various expiry date strings (e.g. '30-11-2026', '31/12/2026', '31-08-2026 //')
    into Django-compatible YYYY-MM-DD date.
    """
    if not date_str:
        return None
    
    # Strip garbage characters
    cleaned = re.sub(r'[\s//]+', '', date_str)
    
    # Try DD-MM-YYYY or DD/MM/YYYY
    for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d'):
        try:
            return datetime.strptime(cleaned, fmt).date().strftime('%Y-%m-%d')
        except ValueError:
            pass
            
    # Try MM-YYYY or MM/YYYY (Assume last day of the month)
    for fmt in ('%m-%Y', '%m/%Y', '%b-%Y', '%Y-%m'):
        try:
            dt = datetime.strptime(cleaned, fmt)
            # Find last day of month
            import calendar
            last_day = calendar.monthrange(dt.year, dt.month)[1]
            return datetime(dt.year, dt.month, last_day).date().strftime('%Y-%m-%d')
        except ValueError:
            pass
            
    # Fallback to current year end or a standard date if unparseable
    return None

def extract_conversion_and_type(packing_str, name_str=""):
    """
    Extracts conversion factor and guesses product type from packing and name.
    """
    packing = clean_value(packing_str).upper()
    name = clean_value(name_str).upper()
    combined = f"{packing} {name}"
    
    conv_factor = 1
    prod_type = "TABLET" # default
    
    if not packing:
        # Try to extract conversion from name
        digits = re.findall(r'\d+', name)
        if digits:
            conv_factor = int(digits[0])
        
    # Check for digits in packing
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


# ----------------------------------------------------
# Parse Company Master
# ----------------------------------------------------
import re


def parse_companies(rows):

    companies = []

    junk_patterns = [

        "PRINTED ON",
        "PAGE NO",
        "MASTER LIST",
        "COMPANY NAME",
        "SHORT NAME",
        "----",
        "TULJ",
        "COMP"

    ]

    for r in rows:

        if not r:
            continue

        # ----------------------------------------
        # CLEAN ROW
        # ----------------------------------------

        r = [

            str(x).strip()

            for x in r

            if str(x).strip()

        ]

        if not r:
            continue

        row_text = " ".join(r).upper()

        # ----------------------------------------
        # SKIP JUNK
        # ----------------------------------------

        if any(
            j in row_text
            for j in junk_patterns
        ):
            continue

        # separator lines
        if re.match(
            r'^[-\s]+$',
            row_text
        ):
            continue

        # ----------------------------------------
        # EXPECTED FORMAT
        #
        # 1001,SYSTOPIC,SYS
        # ----------------------------------------

        if len(r) < 3:
            continue

        # first column numeric
        if not r[0].isdigit():
            continue

        company_code = r[0]

        company_name = (
            r[1]
            .strip()
            .upper()
        )

        sht_name = (
            r[2]
            .strip()
            .upper()
        )

        if not company_name:
            continue

        companies.append({

            'company_code': company_code,

            'company_name': company_name,

            'sht_name': sht_name[:6]

        })

    return companies

# ----------------------------------------------------
# Parse Supplier Master (Stateful Multi-line Grid & Flat Fallback)
# ----------------------------------------------------
def clean_nested_labels(val):
    labels = [
        "Address", "Res.Add.Line1", "Res.Add.Line2", "Res.Add.Line3", 
        "Res.Add.L", "Res.Add", "Add.L", "City", "Res.Phone", 
        "Phone", "Mobile", "Fax", "Contact", "Purchase Type", 
        "Purchase", "Discount %", "Cr.Days"
    ]
    for label in labels:
        # Match label followed by optional spaces, colon, optional spaces
        val = re.sub(rf'{re.escape(label)}\s*:\s*', '', val, flags=re.IGNORECASE)
    # Clean trailing slashes or backslashes or leading dashes/equals
    val = re.sub(r'[\\/]+$', '', val).strip()
    return val

def is_multiline_supplier_layout(rows):
    """
    Checks if rows contain the multi-line grid layout for suppliers.
    """
    has_name = False
    has_indicators = False
    for r in rows:
        if not r:
            continue
        row_str = " ".join([str(x) for x in r])
        if re.search(r'Name\s*:', row_str, re.IGNORECASE):
            has_name = True
        if (
            re.search(r'Res\.Add', row_str, re.IGNORECASE) or
            re.search(r'Purchase\s+Type', row_str, re.IGNORECASE) or
            re.search(r'Discount\s*%', row_str, re.IGNORECASE) or
            re.search(r'Cr\.Days', row_str, re.IGNORECASE)
        ):
            has_indicators = True
            
        if has_name and has_indicators:
            return True
    return False

def parse_supplier_block(block):

    supplier = {
        'name': '',
        'phone': '',
        'address': '',
        'email': '',
        'gst': '',
        'dl': ''
    }

    address_parts = []

    for row in block:

        for cell in row:

            text = str(cell).strip()

            if not text:
                continue

            upper = text.upper()

            # ---------------------------------
            # NAME
            # ---------------------------------

            if upper.startswith('NAME'):

                match = re.search(
                    r'Name\s*:\s*(?:\[[^\]]+\])?\s*(.*)',
                    text,
                    re.IGNORECASE
                )

                if match:

                    supplier['name'] = (
                        match.group(1)
                        .strip()
                        .upper()
                    )

                continue

            # ---------------------------------
            # ADDRESS
            # ---------------------------------

            elif upper.startswith('ADDRESS'):

                addr = re.sub(
                    r'Address\s*:',
                    '',
                    text,
                    flags=re.IGNORECASE
                ).strip()

                if addr:
                    address_parts.append(addr)

                continue

            # ---------------------------------
            # CITY
            # ---------------------------------

            elif upper.startswith('CITY'):

                city = re.sub(
                    r'City\s*:',
                    '',
                    text,
                    flags=re.IGNORECASE
                ).strip()

                if city:
                    address_parts.append(city)

                continue

            # ---------------------------------
            # PHONE
            # ---------------------------------

            elif upper.startswith('PHONE'):

                phone = re.sub(
                    r'Phone\s*:',
                    '',
                    text,
                    flags=re.IGNORECASE
                )

                phone = re.sub(
                    r'[^\d]',
                    '',
                    phone
                )

                if phone:
                    supplier['phone'] = phone

                continue

            # ---------------------------------
            # EMAIL
            # ---------------------------------

            elif 'EMAIL' in upper:

                email = text.split(':')[-1].strip()

                supplier['email'] = email

                continue

            # ---------------------------------
            # GST
            # ---------------------------------

            elif 'GST' in upper:

                gst = text.split(':')[-1].strip()

                supplier['gst'] = gst.upper()

                continue

            # ---------------------------------
            # DL NUMBER
            # ---------------------------------

            elif 'DL' in upper:

                dl = text.split(':')[-1].strip()

                supplier['dl'] = dl.upper()

                continue

    # Merge address properly
    supplier['address'] = ", ".join(
        [x for x in address_parts if x]
    )

    # fallback phone
    if not supplier['phone']:
        supplier['phone'] = '0000000000'

    return supplier

def parse_suppliers_from_rows_multiline(rows):
    """
    Groups and parses rows in the multi-line grid layout.
    """
    blocks = []
    current_block = []
    
    for r in rows:
        row_str = " ".join([str(x) for x in r]).strip()
        if not row_str:
            continue
            
        # Check if any cell starts a new supplier
        is_new_supplier = False
        for cell in r:
            if re.match(r'^Name\s*:', str(cell).strip(), re.IGNORECASE):
                is_new_supplier = True
                break
                
        if is_new_supplier:
            if current_block:
                blocks.append(current_block)
            current_block = [r]
        else:
            if current_block:
                current_block.append(r)
                
    if current_block:
        blocks.append(current_block)
        
    suppliers = []
    for block in blocks:
        # Verify first row starts with Name : to filter out random headers
        if any(re.match(r'^Name\s*:', str(cell).strip(), re.IGNORECASE) for cell in block[0]):
            supplier = parse_supplier_block(block)
            if supplier['name']:
                suppliers.append(supplier)
                
    return suppliers

def parse_suppliers_from_text(text_content):

    import re

    suppliers = []

    current = None

    lines = text_content.splitlines()

    for raw_line in lines:

        line = str(raw_line).strip()

        if not line:
            continue

        # remove csv junk
        line = line.strip(',')

        upper = line.upper()

        # =====================================
        # NEW SUPPLIER
        # =====================================

        if re.search(r'NAME\s*:', upper):

            # save previous
            if current and current.get('name'):

                suppliers.append(current)

            current = {
                'name': '',
                'phone': '0000000000',
                'address': '',
                'email': '',
                'gst': '',
                'dl': ''
            }

            match = re.search(
                r'NAME\s*:\s*(?:\[[^\]]+\])?\s*(.*)',
                line,
                re.IGNORECASE
            )

            if match:

                name = (
                    match.group(1)
                    .replace(',', '')
                    .strip()
                    .upper()
                )

                current['name'] = name

            continue

        # =====================================
        # ADDRESS
        # =====================================

        if re.search(r'ADDRESS\s*:', upper):

            if current:

                match = re.search(
                    r'ADDRESS\s*:\s*(.*)',
                    line,
                    re.IGNORECASE
                )

                if match:

                    addr = (
                        match.group(1)
                        .split('Res.Add')[0]
                        .replace('"', '')
                        .strip(' ,')
                    )

                    current['address'] = addr

            continue

        # =====================================
        # CITY
        # =====================================

        if re.search(r'CITY\s*:', upper):

            if current:

                match = re.search(
                    r'CITY\s*:\s*(.*)',
                    line,
                    re.IGNORECASE
                )

                if match:

                    city = (
                        match.group(1)
                        .split(',')[0]
                        .strip()
                    )

                    if city and city != '-':

                        if current['address']:

                            current['address'] += f", {city}"

                        else:

                            current['address'] = city

            continue

        # =====================================
        # PHONE
        # =====================================

        if re.search(r'PHONE\s*:', upper):

            if current:

                nums = re.findall(r'\d{10}', line)

                if nums:

                    current['phone'] = nums[0]

            continue

        # =====================================
        # GST
        # =====================================

        if 'GST' in upper:

            if current:

                nums = re.findall(
                    r'[0-9A-Z]{15}',
                    upper
                )

                if nums:

                    current['gst'] = nums[0]

        # =====================================
        # DL
        # =====================================

        if 'DL' in upper:

            if current:

                dl = line.split(':')[-1].strip()

                if dl and dl != '-':

                    current['dl'] = dl

    # append last supplier
    if current and current.get('name'):

        suppliers.append(current)

    print("==== PARSED SUPPLIERS ====")
    print(suppliers[:5])

    return suppliers

def parse_suppliers_from_rows(rows):
    """
    Parses suppliers from flat CSV/Excel rows or groups multi-line layouts dynamically.
    """
    if is_multiline_supplier_layout(rows):
        return parse_suppliers_from_rows_multiline(rows)
        
    # Standard flat row fallback
    suppliers = []
    for r in rows:
        if len(r) < 1:
            continue
        # Skip header rows
        if r[0].upper() in ["NAME", "SUPPLIER", "SUPPLIER NAME", "CODE"]:
            continue
            
        supplier = {
            'name': '',
            'code': '',
            'phone': '',
            'address': '',
            'email': '',
            'gst': '',
            'dl': ''
        }
        
        # Greedy assignment based on column count
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
            # Multi column mapping
            supplier['name'] = r[0].upper()
            supplier['phone'] = re.sub(r'[^\d]+', '', r[1])
            supplier['address'] = r[2]
            supplier['email'] = r[3] if len(r) > 3 else ""
            supplier['gst'] = r[4].upper() if len(r) > 4 else ""
            supplier['dl'] = r[5].upper() if len(r) > 5 else ""

        if supplier['name']:
            suppliers.append(supplier)
    return suppliers


# ----------------------------------------------------
# Parse Product Master
# ----------------------------------------------------
from concurrent.futures import ThreadPoolExecutor, as_completed
import math


MAX_WORKERS = 10
CHUNK_SIZE = 5000


def process_product_chunk(chunk_rows):

    chunk_products = []

    for r in chunk_rows:

        try:

            if len(r) < 1:
                continue

            if is_junk_report_row(r):
                continue

            cleaned = [
                str(x).strip()
                for x in r
                if str(x).strip()
            ]

            if not cleaned:
                continue

            # -----------------------------------
            # DETECT SHIFTED ROWS
            # -----------------------------------

            product_name = ""
            packing = ""
            company = ""

            # CASE:
            # ['1 AL SYP', '30ML']
            if len(cleaned) >= 2 and looks_like_packing(cleaned[1]):

                product_name = cleaned[0]
                packing = cleaned[1]

                if len(cleaned) > 2:
                    company = cleaned[2]

            # CASE:
            # ['30ML', 'HPP']
            elif looks_like_packing(cleaned[0]):

                # invalid shifted row
                continue

            else:

                product_name = cleaned[0]

                if len(cleaned) > 1:
                    packing = cleaned[1]

                if len(cleaned) > 2:
                    company = cleaned[2]

            product_name = product_name.upper().strip()

            if len(product_name) < 3:
                continue

            # EXTRA SAFETY
            if looks_like_packing(product_name):
                continue

            conv_factor, prod_type = extract_conversion_and_type(
                packing,
                product_name
            )

            chunk_products.append({
                'product_name': product_name,
                'product_packing': packing,
                'company_name': company.upper(),
                'hsn_code': '3004',
                'conversion_factor': conv_factor,
                'product_type': prod_type
            })

        except Exception as e:
            print("Row Error:", r)
            print(str(e))

    return chunk_products

# def process_product_chunk(chunk_rows):

#     chunk_products = []

#     for r in chunk_rows:

#         try:

#             if len(r) < 1:
#                 continue

#             # Skip legacy report junk rows (defensive second pass)
#             if is_junk_report_row(r):
#                 continue

#             name = r[0].upper().strip()

#             # Skip if name is too short or purely numeric
#             if len(name) < 2 or name.isdigit():
#                 continue

#             packing = r[1] if len(r) > 1 else "10 TAB"

#             company = r[2].upper() if len(r) > 2 else ""

#             hsn = r[3] if len(r) > 3 else "3004"

#             conv_factor, prod_type = extract_conversion_and_type(
#                 packing,
#                 name
#             )

#             if name:
#                 chunk_products.append({
#                     'product_name': name,
#                     'product_packing': packing,
#                     'company_name': company,
#                     'hsn_code': hsn,
#                     'conversion_factor': conv_factor,
#                     'product_type': prod_type
#                 })

#         except Exception as e:
#             print(f"Error processing row: {r}")
#             print(str(e))

#     return chunk_products


def chunkify(data, chunk_size):

    for i in range(0, len(data), chunk_size):
        yield data[i:i + chunk_size]

def parse_products(rows):

    products = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:

        futures = []

        for chunk in chunkify(rows, CHUNK_SIZE):

            futures.append(
                executor.submit(
                    process_product_chunk,
                    chunk
                )
            )

        for future in as_completed(futures):

            try:
                result = future.result()
                products.extend(result)

            except Exception as e:
                print(f"Thread Error: {str(e)}")

    return products


# ----------------------------------------------------
# Parse Stock & Batches (Stateful Nested Parser)
# ----------------------------------------------------
def parse_stock_batches(rows):
    """
    Parses batch-wise stock statefully.
    Micropro reports have nested batch details beneath a product line.
    
    Columns expected in rows:
    [P.Code/Product Name, MRP, Batch No, Expiry DT, Close stock, Total, Company]
    """
    batches = []
    
    # State tracking variables
    current_product_code = ""
    current_product_name = ""
    current_company = ""
    current_type = "TABLET"
    
    for r in rows:
        if len(r) < 2:
            continue
            
        # Ignore obvious headers
        if any(x in r[0] for x in ["Product Name", "P.Code", "TULJAI MEDICALS", "Products Typewise", "Close"]):
            continue
            
        # Prod.Type header check: e.g. "Prod.Type : []AYURVEDIC[]"
        type_match = re.search(r'Prod\.Type\s*:\s*\[?\]?([^\[\]\:]+)', r[0], re.IGNORECASE)
        if type_match:
            current_type = type_match.group(1).strip().upper()
            continue
            
        # Let's normalize row length to at least 7 cols
        row_cells = r + [""] * (7 - len(r))
        
        # Check if the row is shifted left (nested batch without product name)
        # Shifted left means the expiry date appears at index 2 instead of index 3.
        is_shifted = False
        expiry_idx = -1
        
        for idx in range(len(row_cells)):
            if parse_expiry_date(row_cells[idx]) is not None:
                expiry_idx = idx
                break
                
        if expiry_idx == 2:
            is_shifted = True
        elif expiry_idx == 3:
            is_shifted = False
        else:
            # Fallback check
            col_0 = row_cells[0].strip()
            if col_0.replace('.', '', 1).isdigit() and len(col_0) < 8:
                is_shifted = True
            else:
                is_shifted = False
        
        p_code = ""
        p_name = ""
        mrp_str = ""
        batch_no = ""
        expiry_str = ""
        qty_str = ""
        company = ""
        
        if is_shifted:
            # Nested batch: uses active parent product state
            mrp_str = row_cells[0]
            batch_no = row_cells[1]
            expiry_str = row_cells[2]
            qty_str = row_cells[3]
            company = row_cells[5] or row_cells[4] or current_company
            
            p_code = current_product_code
            p_name = current_product_name
        else:
            # New product row: extracts code, product name, and first batch details
            col_0 = row_cells[0].strip()
            code_name_match = re.match(r'^(\d+)\s+(.*)', col_0)
            if code_name_match:
                p_code = code_name_match.group(1)
                p_name = code_name_match.group(2).strip().upper()
            else:
                # No numeric code prefix, maybe just name
                p_name = col_0.upper()
                p_code = ""
                
            mrp_str = row_cells[1]
            batch_no = row_cells[2]
            expiry_str = row_cells[3]
            qty_str = row_cells[4]
            company = row_cells[6] or row_cells[5]
            
            # Update state
            current_product_code = p_code
            current_product_name = p_name
            current_company = company or current_company
            
        # Clean company name
        company = company.strip() if company else ""
        if company:
            # Remove trailing numbers like "16 AUSHADHI B" or "7 AUSHADHI B" (which is actually print noise representing total close qty!)
            company_clean_match = re.match(r'^\d+\s+(.*)', company)
            if company_clean_match:
                company = company_clean_match.group(1).strip()
            # Remove any trailing "Page : X" or totals
            company = re.sub(r'\d+$', '', company).strip()
        
        # Parse quantities, prices, dates
        try:
            mrp = float(re.sub(r'[^\d\.]+', '', mrp_str)) if mrp_str else 0.0
        except ValueError:
            mrp = 0.0
            
        try:
            qty = int(re.sub(r'[^\d]+', '', qty_str)) if qty_str else 0
        except ValueError:
            qty = 0
            
        expiry = parse_expiry_date(expiry_str)
        
        # We only record if we have a valid batch number and product name
        if p_name and batch_no:
            conv_factor, derived_type = extract_conversion_and_type(p_name, p_name)
            batches.append({
                'product_code': p_code,
                'product_name': p_name,
                'product_type': current_type if current_type != "TABLET" else derived_type,
                'conversion_factor': conv_factor,
                'mrp': mrp,
                'batch_number': batch_no.upper().strip(),
                'expiry_date': expiry,
                'quantity': qty,
                'company_name': company.strip().upper() if company else current_company.strip().upper()
            })
            
    return batches
