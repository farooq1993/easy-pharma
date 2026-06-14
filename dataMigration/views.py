import json
import uuid
import threading
import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction, connection
from django.core.cache import cache
import os

logger = logging.getLogger('easypharma')

from tenants.models import Tenant

from easypharma.models.Items import (
    Products,
    DrugCompany,
    ProductType,
    ProductContent,
)

from easypharma.models.purchase_invoice import Supplier
from easypharma.models.stock import StockBatch

from dataMigration.models import MigrationLog,MigrationRow

from dataMigration.workers import start_background_migration

from dataMigration.parsers import (
    parse_csv_to_rows,
    parse_text_lines_to_rows,
    parse_companies,
    parse_suppliers_from_text,
    parse_stock_batches,
    parse_product_master_text,
    parse_products_fast,
    parse_product_seed_csv,
)

logger = logging.getLogger(__name__)

# =========================================================
# FILE DECODER
# =========================================================

def decode_uploaded_file(uploaded_file):

    for encoding in ('utf-8', 'cp1252', 'latin1'):

        try:

            uploaded_file.seek(0)

            content = uploaded_file.read().decode(encoding)

            return content, encoding

        except Exception:

            continue

    uploaded_file.seek(0)

    return uploaded_file.read().decode(
        'latin1',
        errors='replace'
    ), 'latin1'


# =========================================================
# ACCESS MIXIN
# =========================================================

class OrganizationRequiredMixin(UserPassesTestMixin):

    def test_func(self):

        user = self.request.user

        return (
            user.is_authenticated
            and user.user_type == 'admin'
        )

    def handle_no_permission(self):

        return JsonResponse({
            'success': False,
            'error': 'Access denied'
        }, status=403)

class MigrationDashboardView(LoginRequiredMixin, OrganizationRequiredMixin, TemplateView):
    template_name = "dataMigration/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Load all active pharmacies for administrative selection
        all_tenants = Tenant.objects.filter(is_active=True).order_by('pharmacy_name')
        
        # Resolve which tenant's history/migration we are focusing on
        selected_tenant = None
        tenant_id = self.request.GET.get('selected_tenant_id')
        if tenant_id:
            try:
                selected_tenant = Tenant.objects.get(id=tenant_id, is_active=True)
            except Tenant.DoesNotExist:
                pass
                
        # Default to first active tenant if none is selected
        if not selected_tenant:
            selected_tenant = all_tenants.first() or self.request.tenant

        logs = MigrationLog.objects.filter(tenant=selected_tenant).order_by('-created_at') if selected_tenant else MigrationLog.objects.none()
        
        # Calculate stats for this tenant
        total_imports = logs.count()
        successful_imports = logs.filter(status='SUCCESS').count()
        rolled_back_imports = logs.filter(status='ROLLED_BACK').count()
        total_records = sum(log.records_count for log in logs.filter(status='SUCCESS'))
        
        context.update({
            'logs': logs,
            'total_imports': total_imports,
            'successful_imports': successful_imports,
            'rolled_back_imports': rolled_back_imports,
            'total_records': total_records,
            'all_tenants': all_tenants,
            'selected_tenant': selected_tenant,
        })
        return context

# =========================================================
# BULK ENRICH
# =========================================================

def _batch_enrich(parsed_data, import_type, tenant):

    PREVIEW_LIMIT = 100

    # =====================================================
    # COMPANY
    # =====================================================

    if import_type == 'company':

        incoming_names = {
            item['company_name'].upper()
            for item in parsed_data
            if item.get('company_name')
        }

        existing = set(
            DrugCompany.objects.filter(
                tenant=tenant,
                company_name__in=incoming_names
            ).values_list(
                'company_name',
                flat=True
            )
        )

        existing_upper = {
            x.upper()
            for x in existing
        }

        for item in parsed_data:

            if item['company_name'].upper() in existing_upper:

                item.update(
                    import_status='Exists',
                    import_status_class='text-warning',
                    notes='Already exists'
                )

            else:

                item.update(
                    import_status='Ready',
                    import_status_class='text-success',
                    notes=''
                )

    # =====================================================
    # SUPPLIER
    # =====================================================

    elif import_type == 'supplier':

        incoming_names = {
            item['name'].upper()
            for item in parsed_data
            if item.get('name')
        }

        existing = set(
            Supplier.objects.filter(
                tenant=tenant,
                name__in=incoming_names
            ).values_list(
                'name',
                flat=True
            )
        )

        existing_upper = {
            x.upper()
            for x in existing
        }

        for item in parsed_data:

            if item['name'].upper() in existing_upper:

                item.update(
                    import_status='Exists',
                    import_status_class='text-warning',
                    notes='Already exists'
                )

            else:

                item.update(
                    import_status='Ready',
                    import_status_class='text-success',
                    notes=''
                )

    # =====================================================
    # PRODUCT
    # =====================================================

    elif import_type == 'product':

        incoming_product_names = {
            item['product_name'].upper()
            for item in parsed_data
            if item.get('product_name')
        }

        incoming_company_names = {
            item.get('company_name', '').upper()
            for item in parsed_data
            if item.get('company_name')
        }

        existing_products = set()

        incoming_product_names = list(incoming_product_names)

        DB_CHUNK = 500

        for i in range(0,len(incoming_product_names),DB_CHUNK):

            chunk = incoming_product_names[i:i + DB_CHUNK]

            rows = Products.objects.filter(
                tenant=tenant,
                product_name__in=chunk
            ).values_list(
                'product_name',
                flat=True
            )

            existing_products.update(rows)

            print(
                f"[PRODUCT ENRICH CHUNK] {i} -> {i + len(chunk)}",
                flush=True
            )
        
        existing_companies = set()

        incoming_company_names = list(incoming_company_names)

        for i in range(0,len(incoming_company_names),500):

            chunk = incoming_company_names[i:i + 500]

            rows = DrugCompany.objects.filter(
                tenant=tenant,
                company_name__in=chunk
            ).values_list(
                'company_name',
                flat=True
            )

            existing_companies.update(rows)

        existing_products_upper = {
            x.upper()
            for x in existing_products
        }

        existing_companies_upper = {
            x.upper()
            for x in existing_companies
        }

        for item in parsed_data:

            pname = item['product_name'].upper()

            cname = item.get(
                'company_name',
                ''
            ).upper()

            if pname in existing_products_upper:

                item.update(
                    import_status='Exists',
                    import_status_class='text-warning',
                    notes='Product exists'
                )

            elif cname and cname not in existing_companies_upper:

                item.update(
                    import_status='Ready (Create Company)',
                    import_status_class='text-info',
                    notes='Company auto create'
                )

            else:

                item.update(
                    import_status='Ready',
                    import_status_class='text-success',
                    notes=''
                )

    # =====================================================
    # PRODUCT SEED  (structured catalog CSV)
    # =====================================================

    elif import_type == 'product_seed':

        incoming_product_names = list({
            item['product_name'].upper()
            for item in parsed_data
            if item.get('product_name')
        })

        incoming_company_names = list({
            item.get('company_name', '').upper()
            for item in parsed_data
            if item.get('company_name')
        })

        existing_products = set(
            Products.objects.filter(
                tenant=tenant, product_name__in=incoming_product_names
            ).values_list('product_name', flat=True)
        ) if incoming_product_names else set()

        existing_companies = set(
            DrugCompany.objects.filter(
                tenant=tenant, company_name__in=incoming_company_names
            ).values_list('company_name', flat=True)
        ) if incoming_company_names else set()

        existing_products_upper  = {x.upper() for x in existing_products}
        existing_companies_upper = {x.upper() for x in existing_companies}

        for item in parsed_data:
            pname = item['product_name'].upper()
            cname = item.get('company_name', '').upper()
            active = item.get('active_ingredients', [])
            ingredients_str = ', '.join(
                i.get('full_description', '') for i in active if i.get('full_description')
            ) if active else ''

            item['ingredients_display'] = ingredients_str or item.get('drug_content', '-')

            if pname in existing_products_upper:
                item.update(import_status='Exists', import_status_class='text-warning', notes='Product exists')
            elif cname and cname not in existing_companies_upper:
                item.update(import_status='Ready (Create Company)', import_status_class='text-info', notes='Company auto create')
            else:
                item.update(import_status='Ready', import_status_class='text-success', notes='')

    # =====================================================
    # STOCK
    # =====================================================

    elif import_type == 'stock':

        incoming_product_names = {
            item['product_name'].upper()
            for item in parsed_data
            if item.get('product_name')
        }

        product_map = {
            p.product_name.upper(): p
            for p in Products.objects.filter(
                tenant=tenant,
                product_name__in=incoming_product_names
            )
        }

        incoming_batches = {
            item.get(
                'batch_number',
                ''
            ).upper()
            for item in parsed_data
            if item.get('batch_number')
        }

        existing_batches = {
            (pid, bn.upper())
            for pid, bn in StockBatch.objects.filter(
                tenant=tenant,
                batch_number__in=incoming_batches
            ).values_list(
                'product_id',
                'batch_number'
            )
        }

        for item in parsed_data:

            pname = item['product_name'].upper()

            prod = product_map.get(pname)

            if not prod:

                item.update(
                    import_status='Ready (Create Product)',
                    import_status_class='text-info',
                    notes='Product auto create'
                )

            elif (
                prod.id,
                item['batch_number'].upper()
            ) in existing_batches:

                item.update(
                    import_status='Duplicate Batch',
                    import_status_class='text-danger',
                    notes='Duplicate batch'
                )

            else:

                item.update(
                    import_status='Ready',
                    import_status_class='text-success',
                    notes=''
                )

    warnings = sum(
        1
        for x in parsed_data
        if 'Exists' in x.get('import_status', '')
    )

    preview_data = parsed_data[:PREVIEW_LIMIT]

    print(f"[ENRICH DONE] warnings={warnings}", flush=True)

    return preview_data, {
        'total': len(parsed_data),
        'preview_count': len(preview_data),
        'warnings': warnings,
        'is_truncated': len(parsed_data) > PREVIEW_LIMIT,
    }


# =========================================================
# BACKGROUND PARSE JOB
# =========================================================

def _run_parse_job(
    job_id,
    import_type,
    input_method,
    content,
    drop_first_col,
    tenant_id
):

    CACHE_KEY = f'parse_job_{job_id}'

    try:

        cache.set(
            CACHE_KEY,
            {
                'status': 'parsing',
                'progress': 15
            },
            timeout=3600
        )

        # Initialise so cache.set never raises NameError if a branch is skipped
        parsed_data = []

        # =====================================================
        # SUPPLIER
        # =====================================================

        if import_type == 'supplier':

            parsed_data = parse_suppliers_from_text(
                content
            )

        # =====================================================
        # COMPANY
        # =====================================================

        elif import_type == 'company':

            if input_method == 'file':

                rows = parse_csv_to_rows(
                    content,
                    drop_first_column=False
                )

            else:

                rows = parse_text_lines_to_rows(
                    content,
                    drop_first_column=False
                )

            logger.info(f"[COMPANY] TOTAL RAW ROWS={len(rows)}")

            if rows:
                logger.info(f"[COMPANY SAMPLE ROW] {rows[0]}")

            # ==============================================
            # EXTRA CLEANING
            # ==============================================

            cleaned_rows = []

            junk_words = [
                'PRINTED ON',
                'PAGE NO',
                'MASTER LIST',
                'COMP ANY',
                'COMPANY MASTER',
                'SHORT NAME',
                'CODE'
            ]

            skipped = 0

            for r in rows:

                try:

                    row_text = " ".join(
                        [str(x).strip().upper() for x in r]
                    )

                    if not row_text:
                        skipped += 1
                        continue

                    if any(j in row_text for j in junk_words):
                        skipped += 1
                        continue

                    cleaned_rows.append(r)

                except Exception:
                    skipped += 1

            logger.info(f"[COMPANY CLEANED ROWS]={len(cleaned_rows)}")
            logger.info(f"[COMPANY SKIPPED]={skipped}")

            parsed_data = parse_companies(
                cleaned_rows
            )

            logger.info(f"[COMPANY PARSED]={len(parsed_data)}")

            if parsed_data:
                logger.info(f"[COMPANY FIRST ITEM]={parsed_data[0]}")

            logger.info("=" * 80)

        # =====================================================
        # PRODUCT
        # =====================================================

        elif import_type == 'product':

            if input_method == 'text':

                parsed_data = parse_product_master_text(
                    content
                )

            else:

                rows = parse_csv_to_rows(
                    content,
                    drop_first_column=False
                )

                parsed_data = parse_products_fast(
                    rows
                )

        # =====================================================
        # PRODUCT SEED  (structured catalog TSV/CSV)
        # =====================================================

        elif import_type == 'product_seed':

            print("[PRODUCT SEED] Parsing structured catalog file", flush=True)
            parsed_data = parse_product_seed_csv(content)
            print(f"[PRODUCT SEED PARSED]={len(parsed_data)}", flush=True)
            if parsed_data:
                print(f"[PRODUCT SEED FIRST ITEM]={parsed_data[0]}", flush=True)

        # =====================================================
        # STOCK
        # =====================================================

        elif import_type == 'stock':

            print("=" * 80, flush=True)
            print("[STOCK IMPORT START]", flush=True)
            print(f"INPUT METHOD={input_method}", flush=True)

            # =================================================
            # AUTO DETECT FORMAT
            # =================================================

            first_part = content[:1000]

            is_csv = (
                ',' in first_part
                or '\t' in first_part
            )

            if input_method == 'file' and is_csv:

                print(
                    "[STOCK] CSV/TAB format detected",
                    flush=True
                )

                rows = parse_csv_to_rows(
                    content,
                    drop_first_column=False
                )

            else:

                print(
                    "[STOCK] TEXT format detected",
                    flush=True
                )

                rows = parse_text_lines_to_rows(
                    content,
                    drop_first_column=False
                )

            print(
                f"[STOCK RAW ROWS]={len(rows)}",
                flush=True
            )

            if rows:
                print(
                    f"[STOCK SAMPLE ROW]={rows[0]}",
                    flush=True
                )

            # =================================================
            # REMOVE EMPTY/JUNK ROWS
            # =================================================

            cleaned_rows = []

            skipped = 0

            junk_words = [
                'PRINTED ON',
                'PAGE NO',
                'STOCK',
                'BATCH',
                '----'
            ]

            for r in rows:

                try:

                    if not r:
                        skipped += 1
                        continue

                    row_text = " ".join(
                        [str(x).strip().upper() for x in r]
                    )

                    if not row_text.strip():
                        skipped += 1
                        continue

                    if any(j in row_text for j in junk_words):
                        skipped += 1
                        continue

                    cleaned_rows.append(r)

                except Exception:

                    skipped += 1

            print(
                f"[STOCK CLEANED ROWS]={len(cleaned_rows)}",
                flush=True
            )

            print(
                f"[STOCK SKIPPED]={skipped}",
                flush=True
            )

            parsed_data = parse_stock_batches(
                cleaned_rows
            )

            print(
                f"[STOCK PARSED]={len(parsed_data)}",
                flush=True
            )

            if parsed_data:

                print(
                    f"[STOCK FIRST ITEM]={parsed_data[0]}",
                    flush=True
                )

            print("=" * 80, flush=True)
        # =====================================================
        # CACHE PARSED DATA
        # =====================================================

        cache.set(
            f'parsed_data_{job_id}',
            parsed_data,
            timeout=3600
        )

        cache.set(
            CACHE_KEY,
            {
                'status': 'enriching',
                'progress': 60
            },
            timeout=3600
        )

        tenant = Tenant.objects.get(
            id=tenant_id
        )

        preview_data, summary = _batch_enrich(
            parsed_data,
            import_type,
            tenant
        )

        cache.set(
            CACHE_KEY,
            {
                'status': 'done',
                'progress': 100,
                'data': preview_data,
                'summary': summary,
            },
            timeout=3600
        )

        print(
            f"[PARSE JOB DONE] {job_id}",
            flush=True
        )

    except Exception as exc:

        import traceback

        traceback.print_exc()

        cache.set(
            CACHE_KEY,
            {
                'status': 'error',
                'error': str(exc)
            },
            timeout=3600
        )

    finally:

        connection.close()


# =========================================================
# PARSE VIEW
# =========================================================

class MigrationParseView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    
    def post(self, request, *args, **kwargs):
        import_type = request.POST.get('import_type')

        # ==================== CHUNKED UPLOAD (Large File) ====================
        if request.POST.get('is_chunked') == 'true':
            return self._handle_chunked_upload(request, import_type)

        # ==================== NORMAL FLOW (Small File) ====================
        input_method = request.POST.get('input_method')
        drop_first_col = request.POST.get('drop_first_column') == 'true'

        content = ''

        if input_method == 'file':
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return JsonResponse({'success': False, 'error': 'No file uploaded'})
            content, enc = decode_uploaded_file(uploaded_file)
        else:
            content = request.POST.get('raw_text', '')

        if not content.strip():
            return JsonResponse({'success': False, 'error': 'No content provided'})

        tenant_id = request.POST.get('selected_tenant_id')
        tenant = get_object_or_404(Tenant, id=tenant_id) if tenant_id else request.tenant

        # PRODUCT SEED Direct Parse
        if import_type == 'product_seed':
            try:
                parsed_data = parse_product_seed_csv(content)
                preview_data, summary = _batch_enrich(parsed_data, import_type, tenant)

                job_id = str(uuid.uuid4())
                cache.set(f'parsed_data_{job_id}', parsed_data, timeout=7200)

                return JsonResponse({
                    'success': True,
                    'status': 'done',
                    'progress': 100,
                    'job_id': job_id,
                    'data': preview_data[:100],
                    'summary': summary,
                    'total_records': len(parsed_data)
                })
            except Exception as e:
                logger.error(f"[PRODUCT SEED] Parsing failed: {str(e)}")
                return JsonResponse({'success': False, 'error': str(e)}, status=400)

        # Other types - Background
        job_id = str(uuid.uuid4())
        cache.set(f'parse_job_{job_id}', {'status': 'queued', 'progress': 5}, timeout=7200)

        t = threading.Thread(
            target=_run_parse_job,
            args=(job_id, import_type, input_method, content, drop_first_col, tenant.id),
            daemon=True
        )
        t.start()

        return JsonResponse({'success': True, 'job_id': job_id})

    # ===================== CHUNKED UPLOAD METHODS =====================
    def _handle_chunked_upload(self, request, import_type):
        try:
            chunk_index = int(request.POST.get('chunk_index', 0))
            total_chunks = int(request.POST.get('total_chunks', 1))
            header_row = request.POST.get('header_row', '')
            tenant_id = request.POST.get('selected_tenant_id')
            job_id = request.POST.get('job_id') or str(uuid.uuid4())

            chunk_file = request.FILES.get('chunk')
            if not chunk_file:
                return JsonResponse({'success': False, 'error': 'No chunk received'}, status=400)

            chunk_content, _ = decode_uploaded_file(chunk_file)

            if not header_row.strip():
                return JsonResponse({'success': False, 'error': 'Missing header_row'}, status=400)

            tenant = get_object_or_404(Tenant, id=tenant_id) if tenant_id else request.tenant

            # Prepend header so DictReader works on this slice
            full_chunk = header_row.strip() + '\n' + chunk_content

            chunk_parsed = parse_product_seed_csv(full_chunk)

            if chunk_parsed:
                # Enrich just this chunk (DB IN-queries already internally chunked to 500)
                _batch_enrich(chunk_parsed, import_type, tenant)

                # Persist incrementally
                base_order = chunk_index * 1_000_000  # large gap so ordering across chunks is stable
                MigrationRow.objects.bulk_create([
                    MigrationRow(
                        job_id=job_id,
                        tenant=tenant,
                        order=base_order + i,
                        data=row
                    )
                    for i, row in enumerate(chunk_parsed)
                ])

            if chunk_index == total_chunks - 1:
                return self._finalize_chunked_job(job_id, tenant)

            return JsonResponse({
                'success': True,
                'chunk_index': chunk_index,
                'progress': round(((chunk_index + 1) / total_chunks) * 100, 1),
                'job_id': job_id,
                'message': f'Chunk {chunk_index + 1}/{total_chunks} processed'
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)


    def _finalize_chunked_job(self, job_id, tenant):
        try:
            qs = MigrationRow.objects.filter(job_id=job_id, tenant=tenant).order_by('order')

            total = qs.count()
            preview = [r.data for r in qs[:100]]
            warnings = qs.filter(data__import_status__icontains='Exists').count()

            return JsonResponse({
                'success': True,
                'status': 'done',
                'job_id': job_id,
                'data': preview,
                'summary': {
                    'total': total,
                    'preview_count': len(preview),
                    'warnings': warnings,
                    'is_truncated': total > 100,
                },
                'total_records': total,
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    # def _process_complete_file(self, temp_dir, total_chunks, import_type, tenant_id, job_id, original_name):
    #     try:
    #         final_path = os.path.join(temp_dir, f"combined_{original_name}")

    #         with open(final_path, 'wb') as outfile:
    #             for i in range(total_chunks):
    #                 chunk_path = os.path.join(temp_dir, f"chunk_{i:03d}.part")
    #                 with open(chunk_path, 'rb') as infile:
    #                     outfile.write(infile.read())

    #         with open(final_path, 'r', encoding='utf-8', errors='replace') as f:
    #             content = f.read()

    #         parsed_data = parse_product_seed_csv(content)

    #         cache.set(f'parsed_data_{job_id}', parsed_data, timeout=7200)

    #         import shutil
    #         shutil.rmtree(temp_dir, ignore_errors=True)

    #         tenant = Tenant.objects.get(id=tenant_id)
    #         preview_data, summary = _batch_enrich(parsed_data, import_type, tenant)

    #         return JsonResponse({
    #             'success': True,
    #             'status': 'done',
    #             'job_id': job_id,
    #             'data': preview_data[:100],
    #             'summary': summary,
    #             'total_records': len(parsed_data)
    #         })

    #     except Exception as e:
    #         import traceback
    #         traceback.print_exc()
    #         return JsonResponse({'success': False, 'error': str(e)}, status=500)

# =========================================================
# PARSE STATUS VIEW
# =========================================================

class MigrationParseStatusView(
    LoginRequiredMixin,
    OrganizationRequiredMixin,
    View
):

    def get(self, request, job_id, *args, **kwargs):

        job = cache.get(
            f'parse_job_{job_id}'
        )

        if not job:
            # Job not in cache yet — two possibilities:
            # 1. Thread hasn't started writing yet (race condition on fast poll) → return queued
            # 2. Cache truly expired after long delay → return expired error
            # We distinguish by checking if the job_id looks recent (can't reliably tell),
            # so we return a "queued" status to keep the poller alive for a few more cycles.
            # The frontend already handles "queued" by continuing to poll.
            return JsonResponse({
                'success': True,
                'status': 'queued',
                'progress': 5,
            })

        return JsonResponse({
            'success': True,
            **job
        })


# =========================================================
# IMPORT VIEW
# =========================================================

class MigrationImportView(LoginRequiredMixin, OrganizationRequiredMixin, View):

    def post(self, request, *args, **kwargs):

        import_type = request.POST.get('import_type')
        job_id = request.POST.get('job_id')

        tenant_id = request.POST.get('selected_tenant_id')
        if tenant_id:
            tenant = get_object_or_404(Tenant, id=tenant_id)
        else:
            tenant = request.tenant

        parsed_data = None

        # ==================== 1. Try MigrationRow table (chunked uploads) ====================
        if job_id:
            try:
                job_uuid = uuid.UUID(job_id)
                rows_qs = MigrationRow.objects.filter(
                    job_id=job_uuid, tenant=tenant
                ).order_by('order')

                if rows_qs.exists():
                    parsed_data = [r.data for r in rows_qs]
                    print(f"[IMPORT] Loaded {len(parsed_data)} rows from MigrationRow table", flush=True)
            except (ValueError, TypeError):
                pass

        # ==================== 2. Try cache (small-file / non-chunked uploads) ====================
        if not parsed_data:
            parsed_data = cache.get(f'parsed_data_{job_id}')

        # ==================== 3. FALLBACK RE-PARSING ====================
        if not parsed_data:
            print("[IMPORT FALLBACK] Parsed data expired/missing → Re-parsing now...", flush=True)

            input_method = request.POST.get('input_method')
            drop_first_col = request.POST.get('drop_first_column') == 'true'
            content = ''

            if input_method == 'file':
                uploaded_file = request.FILES.get('file')
                if uploaded_file:
                    content, _ = decode_uploaded_file(uploaded_file)
            else:
                content = request.POST.get('raw_text', '')

            if not content.strip():
                return JsonResponse({
                    'success': False,
                    'error': 'Parsed data expired and no input found to re-parse'
                })

            try:
                if import_type == 'product_seed':
                    parsed_data = parse_product_seed_csv(content)
                elif import_type == 'supplier':
                    parsed_data = parse_suppliers_from_text(content)
                elif import_type == 'company':
                    if input_method == 'file':
                        rows = parse_csv_to_rows(content, drop_first_column=False)
                    else:
                        rows = parse_text_lines_to_rows(content, drop_first_column=False)
                    parsed_data = parse_companies(rows)
                elif import_type == 'product':
                    if input_method == 'text':
                        parsed_data = parse_product_master_text(content)
                    else:
                        rows = parse_csv_to_rows(content, drop_first_column=False)
                        parsed_data = parse_products_fast(rows)
                elif import_type == 'stock':
                    if input_method == 'file' and (',' in content[:1000] or '\t' in content[:1000]):
                        rows = parse_csv_to_rows(content, drop_first_column=False)
                    else:
                        rows = parse_text_lines_to_rows(content, drop_first_column=False)
                    parsed_data = parse_stock_batches(rows)
                else:
                    return JsonResponse({
                        'success': False,
                        'error': f'Unsupported import type: {import_type}'
                    })

                print(f"[IMPORT FALLBACK] Successfully re-parsed {len(parsed_data)} records", flush=True)
            except Exception as e:
                import traceback
                traceback.print_exc()
                return JsonResponse({
                    'success': False,
                    'error': f'Re-parsing failed: {str(e)}'
                })

        # ==================== Continue with normal flow ====================
        try:
            log_entry = MigrationLog.objects.create(
                tenant=tenant,
                import_type=import_type,
                source_name='Migration',
                records_count=0,
                imported_by=request.user,
                status='PENDING',
                progress_percent=0,
                metadata={}
            )

            print(f"[IMPORT START] log_id={log_entry.id}, records={len(parsed_data)}", flush=True)

            start_background_migration(
                log_id=log_entry.id,
                parsed_data=parsed_data
            )

            return JsonResponse({
                'success': True,
                'message': 'Import started',
                'log_id': log_entry.id
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'success': False,
                'error': str(e)
            })

# class MigrationImportView(LoginRequiredMixin,OrganizationRequiredMixin,View):

#     def post(self, request, *args, **kwargs):

#         import_type = request.POST.get('import_type')
#         job_id = request.POST.get('job_id')

#         # Try cache first
#         parsed_data = cache.get(f'parsed_data_{job_id}')

#         # ==================== FALLBACK RE-PARSING ====================
#         if not parsed_data:
#             print("[IMPORT FALLBACK] Parsed data expired in cache → Re-parsing now...", flush=True)
            
#             input_method = request.POST.get('input_method')
#             drop_first_col = request.POST.get('drop_first_column') == 'true'
#             content = ''
#             tenant_id = request.POST.get('selected_tenant_id')

#             if input_method == 'file':
#                 uploaded_file = request.FILES.get('file')
#                 if uploaded_file:
#                     content, _ = decode_uploaded_file(uploaded_file)
#             else:
#                 content = request.POST.get('raw_text', '')

#             if not content.strip():
#                 return JsonResponse({
#                     'success': False,
#                     'error': 'Parsed data expired and no input found to re-parse'
#                 })

#             # Re-parse based on type (same logic as parse job)
#             try:
#                 if import_type == 'product_seed':
#                     parsed_data = parse_product_seed_csv(content)
#                 elif import_type == 'supplier':
#                     parsed_data = parse_suppliers_from_text(content)
#                 elif import_type == 'company':
#                     if input_method == 'file':
#                         rows = parse_csv_to_rows(content, drop_first_column=False)
#                     else:
#                         rows = parse_text_lines_to_rows(content, drop_first_column=False)
#                     parsed_data = parse_companies(rows)
#                 elif import_type == 'product':
#                     if input_method == 'text':
#                         parsed_data = parse_product_master_text(content)
#                     else:
#                         rows = parse_csv_to_rows(content, drop_first_column=False)
#                         parsed_data = parse_products_fast(rows)
#                 elif import_type == 'stock':
#                     if input_method == 'file' and (',' in content[:1000] or '\t' in content[:1000]):
#                         rows = parse_csv_to_rows(content, drop_first_column=False)
#                     else:
#                         rows = parse_text_lines_to_rows(content, drop_first_column=False)
#                     parsed_data = parse_stock_batches(rows)
#                 else:
#                     return JsonResponse({
#                         'success': False,
#                         'error': f'Unsupported import type: {import_type}'
#                     })
                
#                 print(f"[IMPORT FALLBACK] Successfully re-parsed {len(parsed_data)} records", flush=True)
#             except Exception as e:
#                 import traceback
#                 traceback.print_exc()
#                 return JsonResponse({
#                     'success': False,
#                     'error': f'Re-parsing failed: {str(e)}'
#                 })

#         # Continue with normal flow
#         tenant_id = request.POST.get('selected_tenant_id')
#         if tenant_id:
#             tenant = get_object_or_404(Tenant, id=tenant_id)
#         else:
#             tenant = request.tenant

#         try:
#             log_entry = MigrationLog.objects.create(
#                 tenant=tenant,
#                 import_type=import_type,
#                 source_name='Migration',
#                 records_count=0,
#                 imported_by=request.user,
#                 status='PENDING',
#                 progress_percent=0,
#                 metadata={}
#             )

#             print(f"[IMPORT START] log_id={log_entry.id}, records={len(parsed_data)}", flush=True)

#             start_background_migration(
#                 log_id=log_entry.id,
#                 parsed_data=parsed_data
#             )

#             return JsonResponse({
#                 'success': True,
#                 'message': 'Import started',
#                 'log_id': log_entry.id
#             })

#         except Exception as e:
#             import traceback
#             traceback.print_exc()
#             return JsonResponse({
#                 'success': False,
#                 'error': str(e)
#             })


class MigrationStatusView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    """
    GET API to poll progress status of a running background migration task.
    """
    def get(self, request, log_id, *args, **kwargs):
        # Dynamically resolve tenant based on administrative choice
        tenant_id = request.GET.get('selected_tenant_id')
        if tenant_id and request.user.user_type == 'admin':
            tenant = get_object_or_404(Tenant, id=tenant_id)
        else:
            tenant = request.tenant
            
        log = get_object_or_404(MigrationLog, id=log_id, tenant=tenant)
        return JsonResponse({
            'success': True,
            'status': log.status,
            'progress': log.progress_percent,
            'records_count': log.records_count,
            'error_message': log.error_message or ''
        })


class MigrationRollbackView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    """
    POST API to delete all records created during a specific migration.
    Reverts catalog dependencies and restores log state.
    """
    def post(self, request, log_id, *args, **kwargs):
        # Dynamically resolve tenant based on administrative choice
        tenant_id = request.POST.get('selected_tenant_id')
        if tenant_id and request.user.user_type == 'admin':
            tenant = get_object_or_404(Tenant, id=tenant_id)
        else:
            tenant = request.tenant
            
        log = get_object_or_404(MigrationLog, id=log_id, tenant=tenant)
        
        if log.status == 'ROLLED_BACK':
            return JsonResponse({'success': False, 'error': 'This migration has already been rolled back!'})
            
        try:
            metadata = log.metadata or {}
            created_ids = metadata.get('created_ids', [])
            dependencies = metadata.get('created_dependencies', {})
            
            with transaction.atomic():
                # 1. Delete direct created records
                if log.import_type == 'company':
                    DrugCompany.objects.filter(id__in=created_ids, tenant=tenant).delete()
                elif log.import_type == 'supplier':
                    Supplier.objects.filter(id__in=created_ids, tenant=tenant).delete()
                elif log.import_type in ('product', 'product_seed'):
                    Products.objects.filter(id__in=created_ids, tenant=tenant).delete()
                elif log.import_type == 'stock':
                    # Delete stock batches first
                    StockBatch.objects.filter(id__in=created_ids, tenant=tenant).delete()
                    
                # 2. Delete auto-created product dependencies (if any) to prevent orphaned junk data
                for model_name, ids in dependencies.items():
                    if not ids:
                        continue
                    if model_name == 'Products':
                        Products.objects.filter(id__in=ids, tenant=tenant).delete()
                    elif model_name == 'DrugCompany':
                        DrugCompany.objects.filter(id__in=ids, tenant=tenant).delete()
                    elif model_name == 'ProductType':
                        ProductType.objects.filter(id__in=ids, tenant=tenant).delete()
                    elif model_name == 'ProductContent':
                        ProductContent.objects.filter(id__in=ids, tenant=tenant).delete()
                        
                # 3. Mark log as Rolled Back
                log.status = 'ROLLED_BACK'
                log.save()
                
            return JsonResponse({
                'success': True,
                'message': f'Rollback successful. Removed created records and cleaned catalog dependencies!'
            })
            
        except Exception as e:
            return JsonResponse({'success': False, 'error': f'Failed to perform rollback: {str(e)}'})


class MigrationRegisterTenantView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    """
    POST API to register a new pharmacy (tenant) and its owner user on the fly.
    """
    def post(self, request, *args, **kwargs):
        from easypharma.models import User
        
        pharmacy_name = request.POST.get('pharmacy_name')
        subdomain = request.POST.get('subdomain')
        address = request.POST.get('address')
        phone = request.POST.get('phone')
        license_number = request.POST.get('license_number')
        gst_number = request.POST.get('gst_number', '')
        owner_username = request.POST.get('owner_username')
        owner_password = request.POST.get('owner_password')
        
        # Validation
        if not all([pharmacy_name, subdomain, address, phone, license_number, owner_username, owner_password]):
            return JsonResponse({'success': False, 'error': 'All fields are required.'})
            
        # Check if subdomain already exists
        if Tenant.objects.filter(subdomain=subdomain).exists():
            return JsonResponse({'success': False, 'error': f"Subdomain '{subdomain}' already exists."})
            
        # Check if username already exists
        if User.objects.filter(username=owner_username).exists():
            return JsonResponse({'success': False, 'error': "Username already exists."})
            
        try:
            with transaction.atomic():
                # Create owner user
                owner = User.objects.create_user(
                    username=owner_username,
                    user_type='tenant_owner',
                    password=owner_password
                )
                
                # Create tenant
                tenant = Tenant(
                    name=pharmacy_name,
                    subdomain=subdomain,
                    pharmacy_name=pharmacy_name,
                    address=address,
                    phone=phone,
                    license_number=license_number,
                    gst_number=gst_number,
                    owner=owner
                )
                tenant.save()
                
                # Link tenant to owner
                owner.tenant = tenant
                owner.save()
                
            return JsonResponse({
                'success': True,
                'message': f"Pharmacy '{pharmacy_name}' registered successfully!",
                'tenant_id': tenant.id,
                'pharmacy_name': tenant.pharmacy_name
            })
        except Exception as e:
            return JsonResponse({'success': False, 'error': f"Failed to register pharmacy: {str(e)}"})