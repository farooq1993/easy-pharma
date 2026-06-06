"""
dataMigration/workers.py  — Fixed + Debug Edition
==================================================
Bugs fixed vs original:
  1. log_entry.save() at success only saved progress_percent — status/records_count/metadata
     were silently discarded. Now saves ALL fields in one call.
  2. log_entry.status = 'PROCESSING' was set but never saved. Added update_fields save.
  3. _save_progress DB-writes every chunk — throttled to every 5th chunk.
  4. Dead pd.DataFrame construction kept for every non-supplier import type — removed
     for company/supplier paths; kept only where cleaned_rows is actually needed.
  5. Added print()-based debug output on every major step (visible in Django terminal).
"""

import threading
import traceback
import logging
import time

import pandas as pd
from django.db import connection
from django.utils import timezone

from tenants.models import Tenant
from easypharma.models.Items import Products, DrugCompany, ProductType, ProductContent, ProductContent,ProductTax,ProductSchedule
from easypharma.models.purchase_invoice import Supplier
from easypharma.models.stock import StockBatch
from dataMigration.models import MigrationLog
from dataMigration.parsers import (
    parse_csv_to_rows,
    parse_text_lines_to_rows,
    parse_companies,
    parse_suppliers_from_rows,
    parse_suppliers_from_text,
    parse_stock_batches,
    parse_product_master_text,
    parse_products_fast,
    parse_product_seed_csv,
)

logger = logging.getLogger(__name__)

DB_CHUNK = 5000
# Progress is written to DB every N chunks to avoid hammering on large files
PROGRESS_SAVE_EVERY = 5

# ─────────────────────────────────────────────────────────────
# Debug helper — always prints to stdout (visible in terminal)
# ─────────────────────────────────────────────────────────────
def dbg(msg, *args):
    formatted = msg % args if args else msg
    logger.info(formatted)


# ─────────────────────────────────────────────────────────────
def start_background_migration(log_id,parsed_data):

    dbg("start_background_migration: log_id=%s parsed_records=%d",log_id,len(parsed_data))

    worker = MigrationBackgroundWorker(log_id,parsed_data)

    worker.daemon = True

    worker.start()

    dbg("Worker thread started: %s",worker.name)


class MigrationBackgroundWorker(threading.Thread):
    def __init__(self, log_id, parsed_data, drop_first_col=False, input_method='text'):
        super().__init__(name=f"migration-{log_id}")
        self.log_id = log_id
        self.parsed_data = parsed_data
        self.drop_first_col = drop_first_col
        self.input_method = input_method

    def run(self):
        overall_start = time.time()
        dbg("=" * 60)
        dbg("Worker RUN start: log_id=%s, thread=%s", self.log_id, self.name)

        # ── Load log entry ────────────────────────────────────────
        try:
            log_entry = MigrationLog.objects.get(id=self.log_id)
        except MigrationLog.DoesNotExist:
            dbg("ERROR: MigrationLog id=%s not found — aborting", self.log_id)
            logger.error("Migration log %s not found", self.log_id)
            return

        tenant = log_entry.tenant
        import_type = log_entry.import_type
        dbg("Log loaded: import_type=%s, tenant=%s (%s)", import_type, tenant.id, tenant)

        # FIX #2: mark PROCESSING and save it immediately
        log_entry.status = 'PROCESSING'
        log_entry.progress_percent = 5
        log_entry.save(update_fields=['status', 'progress_percent'])
        dbg("Status set to PROCESSING (saved)")

        created_primary_keys = []
        created_dependency_keys = {}

        try:
            # ── 1. Parse ──────────────────────────────────────────
            dbg("-" * 40)

            dbg("STEP 1: USING CACHED PARSED DATA")

            parse_start = time.time()

            all_parsed_items = self.parsed_data

            parse_elapsed = time.time() - parse_start

            dbg("Cached parsed items=%d",len(all_parsed_items))

            dbg("FIRST 5 PARSED ITEMS:")

            for x in all_parsed_items[:5]:
                dbg("%s", x)

            parse_elapsed = time.time() - parse_start
            total_items = len(all_parsed_items) or 1
            dbg("STEP 1 DONE: parsed %d items in %.2fs", total_items, parse_elapsed)
            if all_parsed_items:
                dbg("Sample first parsed item: %s", all_parsed_items[0])
            else:
                dbg("WARNING: Parser returned 0 items — check file format / encoding!")

            log_entry.progress_percent = 10
            log_entry.save(update_fields=['progress_percent'])

            # ── 2. Bulk import ────────────────────────────────────
            dbg("-" * 40)
            dbg("STEP 2: Bulk import — %d items for import_type=%s", total_items, import_type)
            import_start = time.time()

            # ── 2. Bulk import ────────────────────────────────────
            if import_type == 'company':
                created_primary_keys, created_dependency_keys = _bulk_import_companies(
                    all_parsed_items, tenant, log_entry, total_items)

            elif import_type == 'supplier':
                created_primary_keys, created_dependency_keys = _bulk_import_suppliers(
                    all_parsed_items, tenant, log_entry, total_items)

            elif import_type in ('product', 'product_seed'):
                created_primary_keys, created_dependency_keys = _bulk_import_products(
                    all_parsed_items, tenant, log_entry, total_items)

            elif import_type == 'stock':
                created_primary_keys, created_dependency_keys = _bulk_import_stock(
                    all_parsed_items, tenant, log_entry, total_items)

            else:
                dbg("ERROR: Unknown import_type=%s", import_type)

            import_elapsed = time.time() - import_start
            dbg("STEP 2 DONE: bulk import took %.2fs, created %d primary records",
                import_elapsed, len(created_primary_keys))

            # ── 3. Mark SUCCESS ───────────────────────────────────
            # FIX #1: save ALL fields in one call — original only saved progress_percent
            log_entry.status = 'SUCCESS'
            log_entry.progress_percent = 100
            log_entry.records_count = len(created_primary_keys)
            log_entry.metadata = {
                'created_ids': created_primary_keys,
                'created_dependencies': created_dependency_keys,
            }
            log_entry.save(update_fields=['status', 'progress_percent', 'records_count', 'metadata'])
            dbg("Status set to SUCCESS, records_count=%d (all fields saved)", len(created_primary_keys))
            dbg("=" * 60)
            dbg("Worker FINISHED: total time %.2fs", time.time() - overall_start)

        except Exception as e:
            elapsed = time.time() - overall_start
            dbg("=" * 60)
            dbg("WORKER EXCEPTION after %.2fs: %s", elapsed, e)
            dbg(traceback.format_exc())
            logger.exception("Worker failed after %.2fs", elapsed)
            log_entry.status = 'FAILED'
            log_entry.error_message = str(e)
            log_entry.progress_percent = 100
            log_entry.save(update_fields=['status', 'error_message', 'progress_percent'])

        finally:
            connection.close()
            dbg("DB connection closed for thread %s", self.name)



# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _chunked(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


# FIX #3: throttle DB writes — only persist every PROGRESS_SAVE_EVERY chunks
def _save_progress(log_entry, done, total, base=10, ceiling=95, chunk_idx=0):
    if chunk_idx % PROGRESS_SAVE_EVERY != 0:
        return
    pct = base + int(done / total * (ceiling - base))
    log_entry.progress_percent = min(pct, ceiling)
    log_entry.save(update_fields=['progress_percent'])
    dbg("Progress saved: %d%%", log_entry.progress_percent)


def _resolve_companies(tenant, names: set) -> dict:
    start = time.time()
    result = {
        c.company_name.upper(): c
        for c in DrugCompany.objects.filter(tenant=tenant, company_name__in=list(names))
    }
    dbg("_resolve_companies: found %d / %d in %.3fs", len(result), len(names), time.time() - start)
    return result


def _resolve_types(tenant, names: set) -> dict:
    start = time.time()
    result = {
        t.name.upper(): t
        for t in ProductType.objects.filter(tenant=tenant, name__in=list(names))
    }
    dbg("_resolve_types: found %d / %d in %.3fs", len(result), len(names), time.time() - start)
    return result


def _resolve_contents(tenant, names: set) -> dict:
    start = time.time()
    result = {
        c.content_name.upper(): c
        for c in ProductContent.objects.filter(tenant=tenant, content_name__in=list(names))
    }
    dbg("_resolve_contents: found %d / %d in %.3fs", len(result), len(names), time.time() - start)
    return result


def _ensure_contents(tenant, names: set, existing: dict):
    start = time.time()
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        dbg("_ensure_contents: creating %d missing contents: %s", len(missing), list(missing)[:10])
        objs = [ProductContent(tenant=tenant, content_name=n) for n in missing]
        ProductContent.objects.bulk_create(objs, ignore_conflicts=True)
        for c in ProductContent.objects.filter(tenant=tenant, content_name__in=list(missing)):
            existing[c.content_name.upper()] = c
            new_ids.append(c.id)
    dbg("_ensure_contents: created %d in %.3fs", len(new_ids), time.time() - start)
    return existing, new_ids


def _resolve_contents(tenant, names: set) -> dict:
    start = time.time()
    result = {
        c.content_name.upper(): c
        for c in ProductContent.objects.filter(tenant=tenant, content_name__in=list(names))
    }
    dbg("_resolve_contents: found %d / %d in %.3fs", len(result), len(names), time.time() - start)
    return result


def _ensure_contents(tenant, names: set, existing: dict):
    start = time.time()
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        dbg("_ensure_contents: creating %d missing contents: %s", len(missing), list(missing)[:10])
        objs = [ProductContent(tenant=tenant, content_name=n) for n in missing]
        ProductContent.objects.bulk_create(objs, ignore_conflicts=True)
        for c in ProductContent.objects.filter(tenant=tenant, content_name__in=list(missing)):
            existing[c.content_name.upper()] = c
            new_ids.append(c.id)
    dbg("_ensure_contents: created %d in %.3fs", len(new_ids), time.time() - start)
    return existing, new_ids


def _ensure_companies(tenant, names: set, existing: dict):
    start = time.time()
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        dbg("_ensure_companies: creating %d missing companies: %s", len(missing), list(missing)[:10])
        objs = [DrugCompany(tenant=tenant, company_name=n, sht_name=n[:6]) for n in missing]
        DrugCompany.objects.bulk_create(objs, ignore_conflicts=True)
        for c in DrugCompany.objects.filter(tenant=tenant, company_name__in=list(missing)):
            existing[c.company_name.upper()] = c
            new_ids.append(c.id)
    dbg("_ensure_companies: created %d in %.3fs", len(new_ids), time.time() - start)
    return existing, new_ids


def _ensure_types(tenant, names: set, existing: dict):
    start = time.time()
    missing = names - set(existing.keys())
    new_ids = []
    if missing:
        dbg("_ensure_types: creating %d missing types: %s", len(missing), list(missing))
        objs = [ProductType(tenant=tenant, name=n) for n in missing]
        ProductType.objects.bulk_create(objs, ignore_conflicts=True)
        for t in ProductType.objects.filter(tenant=tenant, name__in=list(missing)):
            existing[t.name.upper()] = t
            new_ids.append(t.id)
    dbg("_ensure_types: created %d in %.3fs", len(new_ids), time.time() - start)
    return existing, new_ids


# ─────────────────────────────────────────────────────────────
# Bulk importers
# ─────────────────────────────────────────────────────────────

def _bulk_import_companies(items, tenant, log_entry, total_items):
    start_all = time.time()
    dbg("--- _bulk_import_companies: %d items ---", len(items))
    created_ids = []
    import_names = {
        item.get('company_name', '').strip().upper()
        for item in items
            if item.get('company_name')
    }

    existing = set(
        DrugCompany.objects.filter(
            tenant=tenant,
            company_name__in=import_names
        ).values_list('company_name', flat=True)
    )
    # existing = {
    #     c.company_name.upper()
    #     for c in DrugCompany.objects.filter(tenant=tenant).only('company_name')
    # }
    dbg("Existing companies in DB: %d", len(existing))

    total_processed = 0
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        chunk_start = time.time()
        new_objs = []
        skipped = 0
        for item in chunk:
            company_name = item.get('company_name', '').strip().upper()
            if not company_name or company_name in existing:
                skipped += 1
                continue
            sht_name = item.get('sht_name', company_name[:6]).strip().upper()
            new_objs.append(DrugCompany(tenant=tenant, company_name=company_name, sht_name=sht_name[:6]))
            existing.add(company_name)

        dbg("Chunk %d: %d items, %d new, %d skipped (existing/blank)",
            chunk_idx, len(chunk), len(new_objs), skipped)

        if new_objs:
            created = DrugCompany.objects.bulk_create(new_objs, batch_size=1000, ignore_conflicts=True)
            for obj in created:
                if obj.id:
                    created_ids.append(obj.id)
            dbg("Chunk %d: bulk_create inserted %d (ids returned: %d)", chunk_idx, len(new_objs), len(created_ids))

        total_processed += len(chunk)
        _save_progress(log_entry, total_processed, total_items, chunk_idx=chunk_idx)
        dbg("Chunk %d done in %.3fs", chunk_idx, time.time() - chunk_start)

    dbg("_bulk_import_companies DONE: %.2fs, created %d", time.time() - start_all, len(created_ids))
    return created_ids, {}


def _bulk_import_suppliers(items, tenant, log_entry, total_items):
    start_all = time.time()
    dbg("--- _bulk_import_suppliers: %d items ---", len(items))
    dbg("=== SUPPLIER IMPORT START ===")
    dbg("Items received=%d", len(items))

    created_ids = []
    import_names = {
        item.get('name', '').strip().upper()
        for item in items
        if item.get('name')
    }

    existing_names_upper = set(
        Supplier.objects.filter(
            tenant=tenant,
            name__in=import_names
        ).values_list('name', flat=True)
    )

    dbg("Existing suppliers in DB: %d", len(existing_names_upper))

    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        dbg("Before bulk_create chunk=%d", chunk_idx)
        chunk_start = time.time()
        new_objs = []
        skipped = 0
        for item in chunk:
            name = item.get('name', '').strip().upper()
            if not name or name in existing_names_upper:
                skipped += 1
                continue
            new_objs.append(Supplier(
                tenant=tenant,
                name=name,
                phone=item.get('phone') or '0000000000',
                address=item.get('address', ''),
                email=item.get('email', ''),
                gst_number=item.get('gst', ''),
                dl_number=item.get('dl', ''),
            ))
            existing_names_upper.add(name)
            dbg("After bulk_create chunk=%d", chunk_idx)
        dbg("Chunk %d: %d items, %d new, %d skipped", chunk_idx, len(chunk), len(new_objs), skipped)

        if new_objs:
            Supplier.objects.bulk_create(new_objs, batch_size=5000, ignore_conflicts=True)
            inserted_names = [o.name for o in new_objs]
            ids = list(Supplier.objects.filter(tenant=tenant, name__in=inserted_names).values_list('id', flat=True))
            
            created_ids.extend(ids)
            dbg("Chunk %d: inserted %d, fetched %d ids", chunk_idx, len(new_objs), len(ids))

        _save_progress(log_entry, (chunk_idx + 1) * DB_CHUNK, total_items, chunk_idx=chunk_idx)
        dbg("Chunk %d done in %.3fs", chunk_idx, time.time() - chunk_start)

    dbg("_bulk_import_suppliers DONE: %.2fs, created %d", time.time() - start_all, len(created_ids))
    return created_ids, {}


def _bulk_import_products(items, tenant, log_entry, total_items):
    start_all = time.time()
    dbg("--- _bulk_import_products: %d items ---", len(items))
    dep_company_ids = []
    dep_type_ids = []
    dep_content_ids = []
    created_ids = []

    # A. Companies
    dbg("Step A: resolving companies")
    all_comp_names = {item['company_name'].strip().upper() for item in items if item.get('company_name', '').strip()}
    dbg("Unique company names in import: %d", len(all_comp_names))
    company_map = _resolve_companies(tenant, all_comp_names)
    company_map, dep_company_ids = _ensure_companies(tenant, all_comp_names, company_map)
    log_entry.progress_percent = 25
    log_entry.save(update_fields=['progress_percent'])

    # B. Product types
    dbg("Step B: resolving product types")
    all_type_names = {item.get('product_type', 'OTHER').strip().upper() for item in items if item.get('product_type')}

    # tenant filter hata do
    type_map = {t.name.upper(): t for t in ProductType.objects.all()}

    missing_types = all_type_names - set(type_map.keys())

    for type_name in missing_types:
        obj, created = ProductType.objects.get_or_create(
            name=type_name,
            defaults={
                'tenant': tenant
            }
        )

        type_map[type_name] = obj

        if created:
            dep_type_ids.append(obj.id)

    dbg("Resolved Product Types: %s", list(type_map.keys()))
  
    log_entry.progress_percent = 35
    log_entry.save(update_fields=['progress_percent'])

    # C. Drug contents (primary ingredient)
    dbg("Step C: resolving drug contents")
    all_content_names = {
        item.get('drug_content', '').strip().upper()
        for item in items
        if item.get('drug_content', '').strip()
    }

    dbg("Unique drug contents in import: %d", len(all_content_names))
    content_map = _resolve_contents(tenant, all_content_names)
    content_map, dep_content_ids = _ensure_contents(tenant, all_content_names, content_map)
    log_entry.progress_percent = 40
    log_entry.save(update_fields=['progress_percent'])


    all_schedules = {item.get('schedule', '').strip().upper() for item in items if item.get('schedule', '').strip()}

    try:
        schedule_map = {
            s.schedule_name.strip().upper(): s
            for s in ProductSchedule.objects.filter(tenant=tenant)
            if s.schedule_name
        }
    except Exception as e:
        import traceback
        dbg("Created Product Schedule: %s", e)
        traceback.print_exc()

    for schedule_name in all_schedules:
        if schedule_name not in schedule_map:
            obj, created = ProductSchedule.objects.get_or_create(
                tenant=tenant,
                schedule_name=schedule_name.title()
            )
            schedule_map[schedule_name] = obj

            if created:
                dbg("Created Product Schedule: %s", obj.schedule_name)
   
    # C1. Product Taxes
    dbg("Step C1: resolving product taxes")

    all_tax_rates = set()

    for item in items:
        try:
            tax = item.get("product_tax")

            if tax not in ("", None):
                all_tax_rates.add(int(float(tax)))

        except Exception:
            pass

    tax_map = {
        t.tax_rate: t
        for t in ProductTax.objects.filter(
            tenant=tenant,
            tax_rate__in=all_tax_rates
        )
    }

    # Missing taxes create
    missing_taxes = all_tax_rates - set(tax_map.keys())

    for rate in missing_taxes:
        obj = ProductTax.objects.create(
            tenant=tenant,
            tax_name=f"GST ({rate}%)",
            tax_rate=rate
        )

        tax_map[rate] = obj

    dbg("Resolved Product Taxes: %s", list(tax_map.keys()))

    # D. Existing products
    dbg("Step D: fetching existing product names for tenant")
    step_start = time.time()
    existing_upper = set(
    Products.objects.filter(
        tenant=tenant,
        product_name__in=[
            item['product_name'].strip().upper()
            for item in items
            if item.get('product_name')
        ]).values_list('product_name', flat=True)
    )
   
    dbg("Existing products in DB: %d (fetched in %.2fs)", len(existing_upper), time.time() - step_start)

    # E. Bulk create
    dbg("Step E: bulk creating products in chunks of %d", DB_CHUNK)
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        chunk_start = time.time()
        new_objs = []
        skipped = 0
        for item in chunk:
            name = item['product_name'].strip().upper()
            if not name or name in existing_upper:
                skipped += 1
                continue
            comp_obj    = company_map.get(item.get('company_name', '').strip().upper())
            type_obj    = type_map.get(item.get('product_type', 'OTHER').strip().upper())
            schedule_obj = schedule_map.get(item.get('schedule', '').strip().upper())
            content_obj = content_map.get(item.get('drug_content', '').strip().upper())

            tax_obj = None

            try:
                tax_rate = item.get('product_tax')

                if tax_rate not in ("", None):
                    tax_rate = int(float(tax_rate))
                    tax_obj = tax_map.get(tax_rate)

            except (ValueError, TypeError):
                pass

            new_objs.append(Products(
                tenant=tenant,
                product_name=name,
                product_packing=item.get('product_packing', ''),
                compny_name=comp_obj,
                product_type=type_obj,
                product_schedule=schedule_obj,
                product_content=content_obj,
                product_tax=tax_obj, 
                product_hsn_code=item.get('hsn_code') or '3004',
                conversion_factor=item.get('conversion_factor') or 1,
            ))
            existing_upper.add(name)

        dbg("Chunk %d: %d items, %d new, %d skipped (existing/blank)",
            chunk_idx, len(chunk), len(new_objs), skipped)

        if new_objs:
            Products.objects.bulk_create(new_objs, ignore_conflicts=True)
            inserted_names = [o.product_name for o in new_objs]
            ids = list(Products.objects.filter(
                tenant=tenant, product_name__in=inserted_names
            ).values_list('id', flat=True))
            created_ids.extend(ids)
            dbg("Chunk %d: bulk_create %d, fetched %d ids", chunk_idx, len(new_objs), len(ids))

        done = (chunk_idx + 1) * DB_CHUNK
        _save_progress(log_entry, done, total_items, base=40, ceiling=95, chunk_idx=chunk_idx)
        dbg("Chunk %d done in %.3fs", chunk_idx, time.time() - chunk_start)

    dbg("_bulk_import_products DONE: %.2fs, created %d", time.time() - start_all, len(created_ids))
    return created_ids, {'DrugCompany': dep_company_ids, 'ProductType': dep_type_ids, 'ProductContent': dep_content_ids}


def _bulk_import_stock(items, tenant, log_entry, total_items):
    start_all = time.time()
    dbg("--- _bulk_import_stock: %d items ---", len(items))
    dep_company_ids = []
    dep_type_ids = []
    dep_product_ids = []
    created_ids = []

    # A. Companies
    dbg("Step A: resolving companies")
    all_comp_names = {item.get('company_name', '').strip().upper() for item in items if item.get('company_name', '').strip()}
    company_map = _resolve_companies(tenant, all_comp_names)
    company_map, dep_company_ids = _ensure_companies(tenant, all_comp_names, company_map)

    # B. Types
    dbg("Step B: resolving product types")
    all_type_names = {item.get('product_type', 'OTHER').strip().upper() for item in items}
    type_map = _resolve_types(tenant, all_type_names)
    type_map, dep_type_ids = _ensure_types(tenant, all_type_names, type_map)

    log_entry.progress_percent = 25
    log_entry.save(update_fields=['progress_percent'])

    # C. Products — only query the names actually in this batch
    dbg("Step C: resolving products for this batch")
    step_start = time.time()
    all_prod_names = {item['product_name'].strip().upper() for item in items if item.get('product_name', '').strip()}
    dbg("Unique product names in stock batch: %d", len(all_prod_names))
    product_map = {
        p.product_name.upper(): p
        for p in Products.objects.filter(tenant=tenant, product_name__in=list(all_prod_names))
    }
    dbg("Matched %d / %d products in DB (%.2fs)", len(product_map), len(all_prod_names), time.time() - step_start)

    missing_prods = all_prod_names - set(product_map.keys())
    if missing_prods:
        dbg("Auto-creating %d missing products", len(missing_prods))
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
                compny_name=company_map.get(v.get('company_name', '').strip().upper()),
                product_type=type_map.get(v.get('product_type', 'OTHER').strip().upper()),
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
        dbg("Auto-created %d products in %.2fs", len(missing_prods), time.time() - step_start)
    else:
        dbg("All products already exist in DB — no auto-create needed")

    log_entry.progress_percent = 40
    log_entry.save(update_fields=['progress_percent'])

    # D. Existing batches
    step_start = time.time()
    existing_batches = {
        (pid, bn.upper())
        for pid, bn in StockBatch.objects.filter(tenant=tenant).values_list('product_id', 'batch_number')
    }
    dbg("Existing batch keys in DB: %d (%.2fs)", len(existing_batches), time.time() - step_start)
    today_str = timezone.now().date().strftime('%Y-%m-%d')

    # E. Bulk create stock batches
    dbg("Step E: bulk creating stock batches in chunks of %d", DB_CHUNK)
    for chunk_idx, chunk in enumerate(_chunked(items, DB_CHUNK)):
        chunk_start = time.time()
        new_objs = []
        skipped_no_product = 0
        skipped_no_batch = 0
        skipped_duplicate = 0

        for item in chunk:
            pname = item['product_name'].strip().upper()
            prod_obj = product_map.get(pname)
            if not prod_obj:
                skipped_no_product += 1
                continue
            batch_num = item.get('batch_number', '').strip().upper()
            if not batch_num:
                skipped_no_batch += 1
                continue
            key = (prod_obj.id, batch_num)
            if key in existing_batches:
                skipped_duplicate += 1
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

        dbg("Chunk %d: %d items → %d new | skipped: no_product=%d, no_batch=%d, duplicate=%d",
            chunk_idx, len(chunk), len(new_objs),
            skipped_no_product, skipped_no_batch, skipped_duplicate)

        if new_objs:
            StockBatch.objects.bulk_create(new_objs, ignore_conflicts=True)
            batch_nums = [o.batch_number for o in new_objs]
            ids = list(StockBatch.objects.filter(
                tenant=tenant, batch_number__in=batch_nums
            ).values_list('id', flat=True))
            created_ids.extend(ids)
            dbg("Chunk %d: bulk_create %d, fetched %d ids", chunk_idx, len(new_objs), len(ids))

        _save_progress(log_entry, (chunk_idx + 1) * DB_CHUNK, total_items, base=40, ceiling=95, chunk_idx=chunk_idx)
        dbg("Chunk %d done in %.3fs", chunk_idx, time.time() - chunk_start)

    dbg("_bulk_import_stock DONE: %.2fs, created %d batches", time.time() - start_all, len(created_ids))
    return created_ids, {'DrugCompany': dep_company_ids, 'ProductType': dep_type_ids, 'Products': dep_product_ids}