"""
dataMigration/workers.py  — Optimized drop-in replacement

Key changes vs original:
  - get_or_create() per row  →  bulk_create() per chunk  (10k rows = ~20 DB queries, not 20 000)
  - All company/type lookups resolved upfront in memory (one query each)
  - Exact field names kept from original: compny_name, product_hsn_code, dl_number, etc.
  - Same start_background_migration() signature — views.py needs zero changes
  - Progress reporting kept at same checkpoints
  - Rollback metadata format unchanged
"""

import threading
import io
import traceback
import logging

import pandas as pd
from django.db import transaction, connection
from django.utils import timezone

from tenants.models import Tenant
from easypharma.models.Items import Products, DrugCompany, ProductType
from easypharma.models.purchase_invoice import Supplier
from easypharma.models.stock import StockBatch
from dataMigration.models import MigrationLog
from dataMigration.parsers import (
    parse_csv_to_rows,
    parse_text_lines_to_rows,
    parse_companies,
    parse_suppliers_from_rows,
    parse_suppliers_from_text,
    parse_products,
    parse_stock_batches,
    parse_suppliers_from_rows_multiline,
)

logger = logging.getLogger(__name__)

# ── Tunable constants ─────────────────────────────────────────────────────────
DB_CHUNK    = 500   # rows per bulk_create call
PARSE_CHUNK = 200   # kept same as original for progress granularity

# ── Public entry point (same signature as before) ────────────────────────────

def start_background_migration(log_id, data_content,
                                drop_first_col=False, input_method='text'):
    worker = MigrationBackgroundWorker(
        log_id, data_content, drop_first_col, input_method
    )
    worker.daemon = True
    worker.start()


# ── Worker thread ─────────────────────────────────────────────────────────────

class MigrationBackgroundWorker(threading.Thread):

    def __init__(self, log_id, data_content,
                 drop_first_col=False, input_method='text'):
        super().__init__(name=f"migration-{log_id}")
        self.log_id       = log_id
        self.data_content = data_content
        self.drop_first_col = drop_first_col
        self.input_method   = input_method

    def run(self):
        try:
            log_entry = MigrationLog.objects.get(id=self.log_id)
        except MigrationLog.DoesNotExist:
            return

        tenant      = log_entry.tenant
        import_type = log_entry.import_type

        log_entry.status           = 'PROCESSING'
        log_entry.progress_percent = 5
        log_entry.save()

        created_primary_keys    = []
        created_dependency_keys = {}

        try:
            # ── 1. Parse raw content → list of dicts ──────────────────────
            if import_type == 'supplier' and self.input_method == 'text':
                all_parsed_items = parse_suppliers_from_text(self.data_content)
            else:
                if import_type == 'product':
                    self.drop_first_col = False
                # Tokenise into rows
                if (self.input_method == 'file' and
                        self.data_content.startswith(('"', 'Code', 'Product', 'Name'))):
                    rows = parse_csv_to_rows(
                        self.data_content, drop_first_column=self.drop_first_col
                    )
                else:
                    rows = parse_text_lines_to_rows(
                        self.data_content, drop_first_column=self.drop_first_col
                    )

                # Light pandas clean (same as original)
                df = pd.DataFrame(rows).fillna('').astype(str)
                cleaned_rows = [
                    r for r in df.values.tolist()
                    if " ".join(r).strip() and
                       not any(x in " ".join(r)
                               for x in ["Page No", "Printed on", "Products Typewise"])
                ]

                if import_type == 'company':
                    drop_first_col = False
                    parsed_data = parse_companies(rows)
                    all_parsed_items = parsed_data
                    total_items = len(all_parsed_items)
                    # all_parsed_items = parse_companies(cleaned_rows)
                    _bulk_import_companies(
                        all_parsed_items,
                        tenant,
                        log_entry,
                        total_items
                    )
                elif import_type == 'supplier':

                    all_parsed_items = parse_suppliers_from_text(self.data_content)
                    
                
                elif import_type == 'product':
                    if self.input_method == 'text':
                        all_parsed_items = parse_product_master_text(self.data_content)
                    else:
                        all_parsed_items = parse_products(cleaned_rows)
    
                elif import_type == 'stock':
                    all_parsed_items = parse_stock_batches(cleaned_rows)
                else:
                    all_parsed_items = []

            total_items = len(all_parsed_items) or 1
            log_entry.progress_percent = 10
            log_entry.save()

            # ── 2. Route to bulk importer ──────────────────────────────────
            if import_type == 'company':
                created_primary_keys, created_dependency_keys = \
                    _bulk_import_companies(all_parsed_items, tenant, log_entry, total_items)

            elif import_type == 'supplier':
                created_primary_keys, created_dependency_keys = \
                    _bulk_import_suppliers(all_parsed_items, tenant, log_entry, total_items)

            elif import_type == 'product':
                created_primary_keys, created_dependency_keys = \
                    _bulk_import_products(all_parsed_items, tenant, log_entry, total_items)

            elif import_type == 'stock':
                created_primary_keys, created_dependency_keys = \
                    _bulk_import_stock(all_parsed_items, tenant, log_entry, total_items)

            # ── 3. Mark success ───────────────────────────────────────────
            log_entry.status           = 'SUCCESS'
            log_entry.progress_percent = 100
            log_entry.records_count    = len(created_primary_keys)
            log_entry.metadata         = {
                'created_ids':          created_primary_keys,
                'created_dependencies': created_dependency_keys,
            }
            log_entry.save()

        except Exception as e:
            traceback.print_exc()
            log_entry.status           = 'FAILED'
            log_entry.error_message    = str(e)
            log_entry.progress_percent = 100
            log_entry.save()

        finally:
            connection.close()   # release thread-local DB connection


# ── Shared helpers ────────────────────────────────────────────────────────────

def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _save_progress(log_entry, done, total, base=10, ceiling=95):
    pct = base + int(done / total * (ceiling - base))
    log_entry.progress_percent = min(pct, ceiling)
    log_entry.save(update_fields=['progress_percent'])


# ── Upfront lookup helpers (one query each) ───────────────────────────────────

def _resolve_companies(tenant, names: set) -> dict:
    """Return name.upper() → DrugCompany obj for all names that already exist."""
    return {
        c.company_name.upper(): c
        for c in DrugCompany.objects.filter(
            tenant=tenant,
            company_name__in=list(names)
        )
    }


def _resolve_types(tenant, names: set) -> dict:
    return {
        t.name.upper(): t
        for t in ProductType.objects.filter(
            tenant=tenant,
            name__in=list(names)
        )
    }


def _ensure_companies(tenant, names: set, existing: dict) -> tuple[dict, list]:
    """Create any missing companies in one bulk_create. Returns updated map + new IDs."""
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        objs = [
            DrugCompany(tenant=tenant,
                        company_name=n,
                        sht_name=n[:6])
            for n in missing
        ]
        DrugCompany.objects.bulk_create(objs, ignore_conflicts=True)
        for c in DrugCompany.objects.filter(tenant=tenant, company_name__in=list(missing)):
            existing[c.company_name.upper()] = c
            new_ids.append(c.id)
    return existing, new_ids


def _ensure_types(tenant, names: set, existing: dict) -> tuple[dict, list]:
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        objs = [ProductType(tenant=tenant, name=n) for n in missing]
        ProductType.objects.bulk_create(objs, ignore_conflicts=True)
        for t in ProductType.objects.filter(tenant=tenant, name__in=list(missing)):
            existing[t.name.upper()] = t
            new_ids.append(t.id)
    return existing, new_ids


# ── Company importer ──────────────────────────────────────────────────────────

import re

def parse_companies(rows):

    companies = []

    junk_patterns = [

        "PRINTED ON",
        "PAGE NO",
        "COMPANY MASTER",
        "CODE",
        "SHORT NAME",
        "----",
        "TUL",
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
        # SKIP HEADERS
        # ----------------------------------------

        if any(j in row_text for j in junk_patterns):
            continue

        # separator line
        if re.match(r'^[-\s]+$', row_text):
            continue

        # ----------------------------------------
        # HANDLE DIFFERENT FORMATS
        # ----------------------------------------

        code = ""
        company_name = ""
        sht_name = ""

        # CASE 1
        # ['1001', 'SYSTOPIC', 'SYS']

        if len(r) >= 3:

            if r[0].isdigit():

                code = r[0]

                company_name = r[1]

                sht_name = r[2]

        # CASE 2
        # ['1001 SYSTOPIC SYS']

        elif len(r) == 1:

            parts = r[0].split()

            if len(parts) >= 3:

                if parts[0].isdigit():

                    code = parts[0]

                    sht_name = parts[-1]

                    company_name = " ".join(
                        parts[1:-1]
                    )

        # CASE 3
        # ['1001', 'SYSTOPIC SYS']

        elif len(r) == 2:

            if r[0].isdigit():

                code = r[0]

                second_parts = r[1].split()

                if len(second_parts) >= 2:

                    sht_name = second_parts[-1]

                    company_name = " ".join(
                        second_parts[:-1]
                    )

        # ----------------------------------------
        # FINAL CLEANING
        # ----------------------------------------

        company_name = company_name.strip().upper()

        sht_name = sht_name.strip().upper()

        if not company_name:
            continue

        if len(company_name) < 2:
            continue

        companies.append({

            'company_name': company_name,

            'sht_name': sht_name[:6]

        })

    return companies


# ── Supplier importer ─────────────────────────────────────────────────────────

def _bulk_import_suppliers(items, tenant, log_entry, total_items):
    created_ids = []

    existing_names = set(
        Supplier.objects.filter(tenant=tenant)
        .values_list('name', flat=True)
    )
    existing_names_upper = {n.upper() for n in existing_names}

    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        new_objs = []
        for item in chunk:
            name = item['name'].strip().upper()
            if not name or name in existing_names_upper:
                continue
            new_objs.append(
                Supplier(
                    tenant=tenant,
                    name=name,
                    phone=item.get('phone') or '0000000000',
                    address=item.get('address', ''),
                    email=item.get('email', ''),
                    gst_number=item.get('gst', ''),
                    dl_number=item.get('dl', ''),   # ← your field name
                )
            )
            existing_names_upper.add(name)

        if new_objs:
            Supplier.objects.bulk_create(new_objs, ignore_conflicts=True)
            inserted_names = [o.name for o in new_objs]
            ids = list(
                Supplier.objects.filter(
                    tenant=tenant, name__in=inserted_names
                ).values_list('id', flat=True)
            )
            created_ids.extend(ids)

        _save_progress(log_entry, (chunk_idx + 1) * DB_CHUNK, total_items)

    return created_ids, {}


# ── Product importer ──────────────────────────────────────────────────────────

def _bulk_import_products(items, tenant, log_entry, total_items):
    dep_company_ids = []
    dep_type_ids    = []
    created_ids     = []

    # ── A. Resolve all companies upfront (2 queries max) ──────────────────
    all_comp_names = {
        item['company_name'].strip().upper()
        for item in items
        if item.get('company_name', '').strip()
    }
    company_map = _resolve_companies(tenant, all_comp_names)
    company_map, dep_company_ids = _ensure_companies(tenant, all_comp_names, company_map)

    log_entry.progress_percent = 30
    log_entry.save(update_fields=['progress_percent'])

    # ── B. Resolve all product types upfront ──────────────────────────────
    all_type_names = {
        item.get('product_type', 'OTHER').strip().upper()
        for item in items
    }
    type_map = _resolve_types(tenant, all_type_names)
    type_map, dep_type_ids = _ensure_types(tenant, all_type_names, type_map)

    log_entry.progress_percent = 40
    log_entry.save(update_fields=['progress_percent'])

    # ── C. Existing product names (skip duplicates) ────────────────────────
    existing_names = set(
        Products.objects.filter(tenant=tenant)
        .values_list('product_name', flat=True)
    )
    existing_upper = {n.upper() for n in existing_names}

    # ── D. Bulk create in chunks ───────────────────────────────────────────
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        new_objs = []
        for item in chunk:
            name = item['product_name'].strip().upper()
            if not name or name in existing_upper:
                continue

            comp_obj = company_map.get(item.get('company_name', '').strip().upper())
            type_obj = type_map.get(
                item.get('product_type', 'OTHER').strip().upper()
            )

            new_objs.append(
                Products(
                    tenant=tenant,
                    product_name=name,
                    product_packing=item.get('product_packing', ''),
                    compny_name=comp_obj,           # ← your field name
                    product_type=type_obj,
                    product_hsn_code=item.get('hsn_code') or '3004',  # ← your field name
                    conversion_factor=item.get('conversion_factor') or 1,
                )
            )
            existing_upper.add(name)

        if new_objs:
            Products.objects.bulk_create(new_objs, ignore_conflicts=True)
            inserted_names = [o.product_name for o in new_objs]
            ids = list(
                Products.objects.filter(
                    tenant=tenant, product_name__in=inserted_names
                ).values_list('id', flat=True)
            )
            created_ids.extend(ids)

        # Progress: 40 → 95
        done = (chunk_idx + 1) * DB_CHUNK
        _save_progress(log_entry, done, total_items, base=40, ceiling=95)

    deps = {'DrugCompany': dep_company_ids, 'ProductType': dep_type_ids}
    return created_ids, deps


# ── Stock importer ────────────────────────────────────────────────────────────

def _bulk_import_stock(items, tenant, log_entry, total_items):

    dep_company_ids = []
    dep_type_ids    = []
    dep_product_ids = []
    created_ids     = []

    # ── A. Resolve / create all companies ─────────────────────────────────
    all_comp_names = {
        item.get('company_name', '').strip().upper()
        for item in items
        if item.get('company_name', '').strip()
    }
    company_map = _resolve_companies(tenant, all_comp_names)
    company_map, dep_company_ids = _ensure_companies(tenant, all_comp_names, company_map)

    # ── B. Resolve / create all product types ─────────────────────────────
    all_type_names = {
        item.get('product_type', 'OTHER').strip().upper()
        for item in items
    }
    type_map = _resolve_types(tenant, all_type_names)
    type_map, dep_type_ids = _ensure_types(tenant, all_type_names, type_map)

    log_entry.progress_percent = 25
    log_entry.save(update_fields=['progress_percent'])

    # ── C. Resolve existing products; auto-create missing ones ────────────
    all_prod_names = {
        item['product_name'].strip().upper()
        for item in items
        if item.get('product_name', '').strip()
    }
    product_map = {
        p.product_name.upper(): p
        for p in Products.objects.filter(
            tenant=tenant, product_name__in=list(all_prod_names)
        )
    }

    missing_prods = all_prod_names - set(product_map.keys())
    if missing_prods:
        # Use first occurrence of each product for defaults
        first = {}
        for item in items:
            n = item['product_name'].strip().upper()
            if n in missing_prods and n not in first:
                first[n] = item

        new_prod_objs = [
            Products(
                tenant=tenant,
                product_name=n,
                product_packing=f"{v.get('conversion_factor', 1)} TAB",
                compny_name=company_map.get(
                    v.get('company_name', '').strip().upper()
                ),
                product_type=type_map.get(
                    v.get('product_type', 'OTHER').strip().upper()
                ),
                product_hsn_code='3004',
                conversion_factor=v.get('conversion_factor') or 1,
            )
            for n, v in first.items()
        ]

        for chunk in _chunked(new_prod_objs, DB_CHUNK):
            Products.objects.bulk_create(chunk, ignore_conflicts=True)

        for p in Products.objects.filter(tenant=tenant, product_name__in=list(missing_prods)):
            product_map[p.product_name.upper()] = p
            dep_product_ids.append(p.id)

    log_entry.progress_percent = 40
    log_entry.save(update_fields=['progress_percent'])

    # ── D. Existing batch keys to skip duplicates ─────────────────────────
    existing_batches = {
        (pid, bn.upper())
        for pid, bn in StockBatch.objects.filter(tenant=tenant)
                                         .values_list('product_id', 'batch_number')
    }

    today_str = timezone.now().date().strftime('%Y-%m-%d')

    # ── E. Bulk create StockBatch in chunks ───────────────────────────────
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        new_objs = []
        for item in chunk:
            pname = item['product_name'].strip().upper()
            prod_obj = product_map.get(pname)
            if not prod_obj:
                continue

            batch_num = item.get('batch_number', '').strip().upper()
            if not batch_num:
                continue

            key = (prod_obj.id, batch_num)
            if key in existing_batches:
                continue

            mrp             = float(item.get('mrp') or 0.0)
            purchase_price  = round(mrp * 0.8, 2)
            qty             = int(item.get('quantity') or 0)
            exp_date        = item.get('expiry_date') or today_str

            new_objs.append(
                StockBatch(
                    tenant=tenant,
                    product=prod_obj,
                    batch_number=batch_num,
                    expiry_date=exp_date,
                    purchase_price=purchase_price,
                    mrp=mrp,
                    sale_price=mrp,
                    initial_quantity=qty,
                    current_quantity=qty,
                )
            )
            existing_batches.add(key)

        if new_objs:
            # StockBatch.create() had side-effects in original (stock ledger etc.)
            # If you have post_save signals on StockBatch, replace bulk_create
            # with the loop below instead:
            #   for o in new_objs: o.save()
            StockBatch.objects.bulk_create(new_objs, ignore_conflicts=True)
            batch_nums = [o.batch_number for o in new_objs]
            ids = list(
                StockBatch.objects.filter(
                    tenant=tenant, batch_number__in=batch_nums
                ).values_list('id', flat=True)
            )
            created_ids.extend(ids)

        _save_progress(log_entry,
                       40 + int(((chunk_idx + 1) * DB_CHUNK / total_items) * 55),
                       100)

    deps = {
        'DrugCompany': dep_company_ids,
        'ProductType': dep_type_ids,
        'Products':    dep_product_ids,
    }
    return created_ids, deps

from django.db import transaction


DB_CHUNK = 1000


def _chunked(data, chunk_size):

    for i in range(0, len(data), chunk_size):

        yield data[i:i + chunk_size]


def _bulk_import_companies(items,tenant,log_entry,total_items):

    created_ids = []

    # ----------------------------------------
    # PRELOAD EXISTING COMPANIES
    # ----------------------------------------

    existing = {

        c.company_name.upper()

        for c in DrugCompany.objects.filter(
            tenant=tenant
        ).only('company_name')

    }

    total_processed = 0

    # ----------------------------------------
    # CHUNK PROCESSING
    # ----------------------------------------

    for chunk_idx, chunk in enumerate(

        _chunked(items, DB_CHUNK)

    ):

        new_objs = []

        for item in chunk:

            try:

                company_name = item.get(
                    'company_name',
                    ''
                ).strip().upper()

                if not company_name:
                    continue

                # duplicate prevention
                if company_name in existing:
                    continue

                sht_name = item.get(
                    'sht_name',
                    company_name[:6]
                ).strip().upper()

                obj = DrugCompany(

                    tenant=tenant,

                    company_name=company_name,

                    sht_name=sht_name[:6]

                )

                new_objs.append(obj)

                existing.add(company_name)

            except Exception as e:

                print(
                    "Company Import Error:",
                    str(e)
                )

        # ----------------------------------------
        # BULK INSERT
        # ----------------------------------------

        if new_objs:

            created = DrugCompany.objects.bulk_create(

                new_objs,

                batch_size=1000,

                ignore_conflicts=True

            )

            # collect created IDs
            for obj in created:

                if obj.id:
                    created_ids.append(obj.id)

        # ----------------------------------------
        # SAVE PROGRESS
        # ----------------------------------------

        total_processed += len(chunk)

        _save_progress(

            log_entry,

            total_processed,

            total_items

        )

    print(

        f"Created {len(created_ids)} companies"

    )

    return created_ids, {}