"""
dataMigration/workers.py  — Optimized with detailed logging
"""

import threading
import io
import traceback
import logging
import time
import re

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
    parse_product_master_text,
    parse_products_fast
)

logger = logging.getLogger(__name__)

DB_CHUNK = 5000
PARSE_CHUNK = 200

def start_background_migration(log_id, data_content, drop_first_col=False, input_method='text'):
    worker = MigrationBackgroundWorker(log_id, data_content, drop_first_col, input_method)
    worker.daemon = True
    worker.start()

class MigrationBackgroundWorker(threading.Thread):
    def __init__(self, log_id, data_content, drop_first_col=False, input_method='text'):
        super().__init__(name=f"migration-{log_id}")
        self.log_id = log_id
        self.data_content = data_content
        self.drop_first_col = drop_first_col
        self.input_method = input_method

    def run(self):
        overall_start = time.time()
        try:
            log_entry = MigrationLog.objects.get(id=self.log_id)
        except MigrationLog.DoesNotExist:
            logger.error("Migration log %s not found", self.log_id)
            return
        tenant = log_entry.tenant
        import_type = log_entry.import_type
        logger.info("Worker started: log_id=%s, tenant=%s, import_type=%s, input_method=%s",
                    self.log_id, tenant.id, import_type, self.input_method)
        log_entry.status = 'PROCESSING'
        log_entry.progress_percent = 5
        log_entry.save(update_fields=['progress_percent'])
        created_primary_keys = []
        created_dependency_keys = {}
        try:
            # ── 1. Parse raw content → list of dicts ──────────────────────
            parse_start = time.time()
            if import_type == 'supplier' and self.input_method == 'text':
                all_parsed_items = parse_suppliers_from_text(self.data_content)
            else:
                if import_type == 'product':
                    self.drop_first_col = False
                if (self.input_method == 'file' and
                        self.data_content.startswith(('"', 'Code', 'Product', 'Name'))):
                    rows = parse_csv_to_rows(self.data_content, drop_first_column=self.drop_first_col)
                else:
                    rows = parse_text_lines_to_rows(self.data_content, drop_first_column=self.drop_first_col)
                df = pd.DataFrame(rows).fillna('').astype(str)
                cleaned_rows = [r for r in df.values.tolist() if " ".join(r).strip() and
                                not any(x in " ".join(r) for x in ["Page No", "Printed on", "Products Typewise"])]
                if import_type == 'company':
                    parsed_data = parse_companies(rows)
                    all_parsed_items = parsed_data
                elif import_type == 'supplier':
                    all_parsed_items = parse_suppliers_from_text(self.data_content)
                elif import_type == 'product':
                    if self.input_method == 'text':
                        all_parsed_items = parse_product_master_text(self.data_content)
                    else:
                        all_parsed_items = parse_products_fast(cleaned_rows)
                elif import_type == 'stock':
                    all_parsed_items = parse_stock_batches(cleaned_rows)
                else:
                    all_parsed_items = []
            parse_elapsed = time.time() - parse_start
            total_items = len(all_parsed_items) or 1
            logger.info("Parsing completed in %.2fs, items=%d", parse_elapsed, total_items)
            log_entry.progress_percent = 10
            log_entry.save(update_fields=['progress_percent'])
            # ── 2. Route to bulk importer ──────────────────────────────────
            import_start = time.time()
            if import_type == 'company':
                created_primary_keys, created_dependency_keys = _bulk_import_companies(all_parsed_items, tenant, log_entry, total_items)
            elif import_type == 'supplier':
                created_primary_keys, created_dependency_keys = _bulk_import_suppliers(all_parsed_items, tenant, log_entry, total_items)
            elif import_type == 'product':
                created_primary_keys, created_dependency_keys = _bulk_import_products(all_parsed_items, tenant, log_entry, total_items)
            elif import_type == 'stock':
                created_primary_keys, created_dependency_keys = _bulk_import_stock(all_parsed_items, tenant, log_entry, total_items)
            import_elapsed = time.time() - import_start
            logger.info("Bulk import completed in %.2fs, created %d primary records", import_elapsed, len(created_primary_keys))
            # ── 3. Mark success ───────────────────────────────────────────
            log_entry.status = 'SUCCESS'
            log_entry.progress_percent = 100
            log_entry.records_count = len(created_primary_keys)
            log_entry.metadata = {'created_ids': created_primary_keys, 'created_dependencies': created_dependency_keys}
            log_entry.save(update_fields=['progress_percent'])
            logger.info("Worker finished successfully: total time %.2fs", time.time() - overall_start)
        except Exception as e:
            logger.exception("Worker failed after %.2fs", time.time() - overall_start)
            log_entry.status = 'FAILED'
            log_entry.error_message = str(e)
            log_entry.progress_percent = 100
            log_entry.save(update_fields=['progress_percent'])
        finally:
            connection.close()

def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def _save_progress(log_entry, done, total, base=10, ceiling=95):
    pct = base + int(done / total * (ceiling - base))
    log_entry.progress_percent = min(pct, ceiling)
    log_entry.save(update_fields=['progress_percent'])

def _resolve_companies(tenant, names: set) -> dict:
    start = time.time()
    result = {c.company_name.upper(): c for c in DrugCompany.objects.filter(tenant=tenant, company_name__in=list(names))}
    logger.debug("_resolve_companies: %d names resolved in %.3fs", len(result), time.time()-start)
    return result

def _resolve_types(tenant, names: set) -> dict:
    start = time.time()
    result = {t.name.upper(): t for t in ProductType.objects.filter(tenant=tenant, name__in=list(names))}
    logger.debug("_resolve_types: %d types resolved in %.3fs", len(result), time.time()-start)
    return result

def _ensure_companies(tenant, names: set, existing: dict) -> tuple[dict, list]:
    start = time.time()
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        objs = [DrugCompany(tenant=tenant, company_name=n, sht_name=n[:6]) for n in missing]
        DrugCompany.objects.bulk_create(objs, ignore_conflicts=True)
        for c in DrugCompany.objects.filter(tenant=tenant, company_name__in=list(missing)):
            existing[c.company_name.upper()] = c
            new_ids.append(c.id)
    logger.debug("_ensure_companies: created %d companies in %.3fs", len(new_ids), time.time()-start)
    return existing, new_ids

def _ensure_types(tenant, names: set, existing: dict) -> tuple[dict, list]:
    start = time.time()
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        objs = [ProductType(tenant=tenant, name=n) for n in missing]
        ProductType.objects.bulk_create(objs, ignore_conflicts=True)
        for t in ProductType.objects.filter(tenant=tenant, name__in=list(missing)):
            existing[t.name.upper()] = t
            new_ids.append(t.id)
    logger.debug("_ensure_types: created %d types in %.3fs", len(new_ids), time.time()-start)
    return existing, new_ids

def _bulk_import_companies(items, tenant, log_entry, total_items):
    start_all = time.time()
    logger.info("_bulk_import_companies: starting with %d items", len(items))
    created_ids = []
    existing = {c.company_name.upper() for c in DrugCompany.objects.filter(tenant=tenant).only('company_name')}
    logger.debug("Existing companies count: %d", len(existing))
    total_processed = 0
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        chunk_start = time.time()
        new_objs = []
        for item in chunk:
            company_name = item.get('company_name', '').strip().upper()
            if not company_name or company_name in existing:
                continue
            sht_name = item.get('sht_name', company_name[:6]).strip().upper()
            new_objs.append(DrugCompany(tenant=tenant, company_name=company_name, sht_name=sht_name[:6]))
            existing.add(company_name)
        if new_objs:
            created = DrugCompany.objects.bulk_create(new_objs, batch_size=1000, ignore_conflicts=True)
            for obj in created:
                if obj.id:
                    created_ids.append(obj.id)
        total_processed += len(chunk)
        _save_progress(log_entry, total_processed, total_items)
        logger.debug("Chunk %d: processed %d rows, created %d companies in %.3fs",
                     chunk_idx, len(chunk), len(new_objs), time.time()-chunk_start)
    elapsed = time.time() - start_all
    logger.info("_bulk_import_companies: finished in %.2fs, created %d companies", elapsed, len(created_ids))
    return created_ids, {}

def _bulk_import_suppliers(items, tenant, log_entry, total_items):
    start_all = time.time()
    logger.info("_bulk_import_suppliers: starting with %d items", len(items))
    created_ids = []
    existing_names = set(Supplier.objects.filter(tenant=tenant).values_list('name', flat=True))
    existing_names_upper = {n.upper() for n in existing_names}
    logger.debug("Existing suppliers count: %d", len(existing_names))
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        chunk_start = time.time()
        new_objs = []
        for item in chunk:
            name = item['name'].strip().upper()
            if not name or name in existing_names_upper:
                continue
            new_objs.append(Supplier(
                tenant=tenant,
                name=name,
                phone=item.get('phone') or '0000000000',
                address=item.get('address', ''),
                email=item.get('email', ''),
                gst_number=item.get('gst', ''),
                dl_number=item.get('dl', '')
            ))
            existing_names_upper.add(name)
        if new_objs:
            Supplier.objects.bulk_create(new_objs, batch_size=5000, ignore_conflicts=True)
            inserted_names = [o.name for o in new_objs]
            ids = list(Supplier.objects.filter(tenant=tenant, name__in=inserted_names).values_list('id', flat=True))
            created_ids.extend(ids)
        _save_progress(log_entry, (chunk_idx + 1) * DB_CHUNK, total_items)
        logger.debug("Chunk %d: processed %d rows, created %d suppliers in %.3fs",
                     chunk_idx, len(chunk), len(new_objs), time.time()-chunk_start)
    elapsed = time.time() - start_all
    logger.info("_bulk_import_suppliers: finished in %.2fs, created %d suppliers", elapsed, len(created_ids))
    return created_ids, {}

def _bulk_import_products(items, tenant, log_entry, total_items):
    start_all = time.time()
    logger.info("_bulk_import_products: starting with %d items", len(items))
    dep_company_ids = []
    dep_type_ids = []
    created_ids = []
    # A. Companies
    step_start = time.time()
    all_comp_names = {item['company_name'].strip().upper() for item in items if item.get('company_name', '').strip()}
    company_map = _resolve_companies(tenant, all_comp_names)
    company_map, dep_company_ids = _ensure_companies(tenant, all_comp_names, company_map)
    logger.info("Companies resolved in %.2fs, missing created: %d", time.time()-step_start, len(dep_company_ids))
    log_entry.progress_percent = 30
    log_entry.save(update_fields=['progress_percent'])
    # B. Types
    step_start = time.time()
    all_type_names = {item.get('product_type', 'OTHER').strip().upper() for item in items}
    type_map = _resolve_types(tenant, all_type_names)
    type_map, dep_type_ids = _ensure_types(tenant, all_type_names, type_map)
    logger.info("Types resolved in %.2fs, missing created: %d", time.time()-step_start, len(dep_type_ids))
    log_entry.progress_percent = 40
    log_entry.save(update_fields=['progress_percent'])
    # C. Existing products
    step_start = time.time()
    existing_names = set(Products.objects.filter(tenant=tenant).values_list('product_name', flat=True))
    existing_upper = {n.upper() for n in existing_names}
    logger.info("Fetched %d existing product names in %.2fs", len(existing_upper), time.time()-step_start)
    # D. Bulk create
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        chunk_start = time.time()
        new_objs = []
        for item in chunk:
            name = item['product_name'].strip().upper()
            if not name or name in existing_upper:
                continue
            comp_obj = company_map.get(item.get('company_name', '').strip().upper())
            type_obj = type_map.get(item.get('product_type', 'OTHER').strip().upper())
            new_objs.append(Products(
                tenant=tenant,
                product_name=name,
                product_packing=item.get('product_packing', ''),
                compny_name=comp_obj,
                product_type=type_obj,
                product_hsn_code=item.get('hsn_code') or '3004',
                conversion_factor=item.get('conversion_factor') or 1,
            ))
            existing_upper.add(name)
        if new_objs:
            Products.objects.bulk_create(new_objs, ignore_conflicts=True)
            inserted_names = [o.product_name for o in new_objs]
            ids = list(Products.objects.filter(tenant=tenant, product_name__in=inserted_names).values_list('id', flat=True))
            created_ids.extend(ids)
        done = (chunk_idx + 1) * DB_CHUNK
        _save_progress(log_entry, done, total_items, base=40, ceiling=95)
        logger.debug("Chunk %d: processed %d rows, created %d products in %.3fs",
                     chunk_idx, len(chunk), len(new_objs), time.time()-chunk_start)
    elapsed = time.time() - start_all
    logger.info("_bulk_import_products: finished in %.2fs, created %d products", elapsed, len(created_ids))
    deps = {'DrugCompany': dep_company_ids, 'ProductType': dep_type_ids}
    return created_ids, deps

def _bulk_import_stock(items, tenant, log_entry, total_items):
    start_all = time.time()
    logger.info("_bulk_import_stock: starting with %d items", len(items))
    dep_company_ids = []
    dep_type_ids = []
    dep_product_ids = []
    created_ids = []
    # A. Companies
    step_start = time.time()
    all_comp_names = {item.get('company_name', '').strip().upper() for item in items if item.get('company_name', '').strip()}
    company_map = _resolve_companies(tenant, all_comp_names)
    company_map, dep_company_ids = _ensure_companies(tenant, all_comp_names, company_map)
    logger.info("Companies resolved in %.2fs", time.time()-step_start)
    # B. Types
    step_start = time.time()
    all_type_names = {item.get('product_type', 'OTHER').strip().upper() for item in items}
    type_map = _resolve_types(tenant, all_type_names)
    type_map, dep_type_ids = _ensure_types(tenant, all_type_names, type_map)
    logger.info("Types resolved in %.2fs", time.time()-step_start)
    log_entry.progress_percent = 25
    log_entry.save(update_fields=['progress_percent'])
    # C. Products
    step_start = time.time()
    all_prod_names = {item['product_name'].strip().upper() for item in items if item.get('product_name', '').strip()}
    product_map = {p.product_name.upper(): p for p in Products.objects.filter(tenant=tenant, product_name__in=list(all_prod_names))}
    missing_prods = all_prod_names - set(product_map.keys())
    if missing_prods:
        first = {}
        for item in items:
            n = item['product_name'].strip().upper()
            if n in missing_prods and n not in first:
                first[n] = item
        new_prod_objs = [Products(
            tenant=tenant,
            product_name=n,
            product_packing=f"{v.get('conversion_factor', 1)} TAB",
            compny_name=company_map.get(v.get('company_name', '').strip().upper()),
            product_type=type_map.get(v.get('product_type', 'OTHER').strip().upper()),
            product_hsn_code='3004',
            conversion_factor=v.get('conversion_factor') or 1,
        ) for n, v in first.items()]
        for chunk in _chunked(new_prod_objs, DB_CHUNK):
            Products.objects.bulk_create(chunk, ignore_conflicts=True)
        for p in Products.objects.filter(tenant=tenant, product_name__in=list(missing_prods)):
            product_map[p.product_name.upper()] = p
            dep_product_ids.append(p.id)
        logger.info("Auto-created %d missing products in %.2fs", len(missing_prods), time.time()-step_start)
    else:
        logger.info("All products already exist (%d found)", len(product_map))
    log_entry.progress_percent = 40
    log_entry.save(update_fields=['progress_percent'])
    # D. Existing batches
    step_start = time.time()
    existing_batches = {(pid, bn.upper()) for pid, bn in StockBatch.objects.filter(tenant=tenant).values_list('product_id', 'batch_number')}
    logger.info("Fetched %d existing batch keys in %.2fs", len(existing_batches), time.time()-step_start)
    today_str = timezone.now().date().strftime('%Y-%m-%d')
    # E. Bulk create stock
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        chunk_start = time.time()
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
            mrp = float(item.get('mrp') or 0.0)
            purchase_price = round(mrp * 0.8, 2)
            qty = int(item.get('quantity') or 0)
            exp_date = item.get('expiry_date') or today_str
            new_objs.append(StockBatch(
                tenant=tenant,
                product=prod_obj,
                batch_number=batch_num,
                expiry_date=exp_date,
                purchase_price=purchase_price,
                mrp=mrp,
                sale_price=mrp,
                initial_quantity=qty,
                current_quantity=qty,
            ))
            existing_batches.add(key)
        if new_objs:
            StockBatch.objects.bulk_create(new_objs, ignore_conflicts=True)
            batch_nums = [o.batch_number for o in new_objs]
            ids = list(StockBatch.objects.filter(tenant=tenant, batch_number__in=batch_nums).values_list('id', flat=True))
            created_ids.extend(ids)
        progress = 40 + int(((chunk_idx + 1) * DB_CHUNK / total_items) * 55)
        _save_progress(log_entry, progress, 100, base=0, ceiling=95)
        logger.debug("Chunk %d: processed %d rows, created %d stock batches in %.3fs",
                     chunk_idx, len(chunk), len(new_objs), time.time()-chunk_start)
    elapsed = time.time() - start_all
    logger.info("_bulk_import_stock: finished in %.2fs, created %d stock batches", elapsed, len(created_ids))
    deps = {'DrugCompany': dep_company_ids, 'ProductType': dep_type_ids, 'Products': dep_product_ids}
    return created_ids, deps