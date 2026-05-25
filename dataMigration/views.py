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
from django.utils import timezone

logger = logging.getLogger('easypharma')


def decode_uploaded_file(uploaded_file):
    """
    Robustly decodes an uploaded file trying UTF-8 first,
    then Windows-1252 (cp1252 — most legacy Indian pharmacy software),
    then latin-1 as a guaranteed fallback.
    Returns (content_str, encoding_used).
    """
    for encoding in ('utf-8', 'cp1252', 'latin1'):
        try:
            uploaded_file.seek(0)
            content = uploaded_file.read().decode(encoding)
            return content, encoding
        except (UnicodeDecodeError, LookupError):
            continue
    # Should never reach here since latin1 decodes every byte
    uploaded_file.seek(0)
    return uploaded_file.read().decode('latin1', errors='replace'), 'latin1-replace'

from tenants.models import Tenant
from easypharma.models.Items import Products, DrugCompany, ProductType
from easypharma.models.purchase_invoice import Supplier
from easypharma.models.stock import StockBatch
from dataMigration.models import MigrationLog
from dataMigration.workers import start_background_migration

from dataMigration.parsers import (
    parse_csv_to_rows,
    parse_text_lines_to_rows,
    parse_companies,
    parse_suppliers_from_text,
    parse_suppliers_from_rows,
    parse_products,
    parse_stock_batches,
    is_multiline_supplier_layout,
    parse_product_master_text,
    parse_suppliers_from_rows_multiline
)

class OrganizationRequiredMixin(UserPassesTestMixin):
    """
    Mixin to restrict data migration access solely to SaaS global system Admins.
    """
    def test_func(self):
        user = self.request.user
        return user.is_authenticated and user.user_type == 'admin'

    def handle_no_permission(self):
        if self.request.headers.get('x-requested-with') == 'XMLHttpRequest' or self.request.path.startswith('/migration/parse/') or self.request.path.startswith('/migration/import/') or self.request.path.startswith('/migration/rollback/'):
            return JsonResponse({'success': False, 'error': 'Access Denied: Only system administrators can perform data migration.'}, status=403)
            
        messages.error(self.request, "Access Denied: Only system administrators can access the Data Migration Center.")
        return redirect('home')


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
        return context# ---------------------------------------------------------------------------
# Background parse helpers
# ---------------------------------------------------------------------------

def _batch_enrich(parsed_data, import_type, tenant):
    """
    Enrich all parsed records with DB status in BULK (2-4 queries total).
    This replaces the old per-row query loop that caused 88,000+ DB hits.
    """
    PREVIEW_LIMIT = 100

    if import_type == 'company':
        existing = set(
            DrugCompany.objects.filter(tenant=tenant)
            .values_list('company_name', flat=True)
        )
        existing_up = {n.upper() for n in existing}
        for item in parsed_data:
            if item['company_name'].upper() in existing_up:
                item.update(import_status='Exists (Skip/Update)', import_status_class='text-warning',
                            notes='This company is already registered in your database.')
            else:
                item.update(import_status='Ready', import_status_class='text-success', notes='')

    elif import_type == 'supplier':
        existing = set(
            Supplier.objects.filter(tenant=tenant)
            .values_list('name', flat=True)
        )
        existing_up = {n.upper() for n in existing}
        for item in parsed_data:
            if item['name'].upper() in existing_up:
                item.update(import_status='Exists (Skip/Update)', import_status_class='text-warning',
                            notes='A supplier with this name is already registered.')
            else:
                item.update(import_status='Ready', import_status_class='text-success', notes='')

    elif import_type == 'product':
        existing_companies = {
            n.upper() for n in
            DrugCompany.objects.filter(tenant=tenant).values_list('company_name', flat=True)
        }
        existing_products = {
            n.upper() for n in
            Products.objects.filter(tenant=tenant).values_list('product_name', flat=True)
        }
        for item in parsed_data:
            name = item['product_name'].upper()
            comp = item.get('company_name', '').upper()
            if name in existing_products:
                item.update(import_status='Exists', import_status_class='text-warning',
                            notes='Product already exists in the catalog.')
            elif comp and comp not in existing_companies:
                item.update(import_status='Ready (Auto-Create Company)', import_status_class='text-info',
                            notes=f"Company '{item.get('company_name')}' will be automatically created.")
            else:
                item.update(import_status='Ready', import_status_class='text-success', notes='')

    elif import_type == 'stock':
        product_map = {
            p.product_name.upper(): p
            for p in Products.objects.filter(tenant=tenant)
        }
        existing_batches = {
            (pid, bn.upper())
            for pid, bn in StockBatch.objects.filter(tenant=tenant)
            .values_list('product_id', 'batch_number')
        }
        for item in parsed_data:
            pname = item['product_name'].upper()
            prod = product_map.get(pname)
            if not prod:
                item.update(import_status='Ready (Auto-Create Product)', import_status_class='text-info',
                            notes=f"Product '{item['product_name']}' not in catalog. Will auto-create!")
            elif (prod.id, item['batch_number'].upper()) in existing_batches:
                item.update(import_status='Duplicate Batch', import_status_class='text-danger',
                            notes='This batch number already exists for this product.')
            else:
                item.update(import_status='Ready', import_status_class='text-success', notes='')

    preview_data = parsed_data[:PREVIEW_LIMIT]
    warnings = sum(1 for x in parsed_data
                   if 'Exists' in x.get('import_status', '') or 'Duplicate' in x.get('import_status', ''))
    return preview_data, {
        'total': len(parsed_data),
        'preview_count': len(preview_data),
        'warnings': warnings,
        'is_truncated': len(parsed_data) > PREVIEW_LIMIT,
    }


def _run_parse_job(job_id, import_type, input_method,content, drop_first_col, tenant_id):

    _CACHE_KEY = f'parse_job_{job_id}'

    try:

        cache.set(_CACHE_KEY,
            {'status': 'parsing', 'progress': 15},timeout=3600)

        # =====================================================
        # SUPPLIER IMPORT
        # =====================================================

        if import_type == 'supplier':

            parsed_data = parse_suppliers_from_text(content)
            
        # =====================================================
        # COMPANY IMPORT
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

            parsed_data = parse_companies(rows)

        # =====================================================
        # PRODUCT IMPORT
        # =====================================================

        elif import_type == 'product':

            if input_method == 'text':

                parsed_data = parse_product_master_text(
                    content
                )
                print(f"Parsed {len(parsed_data)} products from text input")

            else:

                rows = parse_csv_to_rows(
                    content,
                    drop_first_column=False
                )

                parsed_data = parse_products(rows)

        # =====================================================
        # STOCK IMPORT
        # =====================================================

        elif import_type == 'stock':

            rows = parse_text_lines_to_rows(
                content,
                drop_first_column=drop_first_col
            )

            parsed_data = parse_stock_batches(rows)

        else:

            parsed_data = []

        logger.info(
            f'Parse job {job_id}: parsed '
            f'{len(parsed_data)} {import_type} records'
        )

        cache.set(
            _CACHE_KEY,
            {'status': 'enriching', 'progress': 60},
            timeout=3600
        )

        tenant = Tenant.objects.get(id=tenant_id)

        preview_data, summary = _batch_enrich(
            parsed_data,
            import_type,
            tenant
        )

        cache.set(_CACHE_KEY, {
            'status': 'done',
            'progress': 100,
            'data': preview_data,
            'summary': summary,
        }, timeout=3600)

    except Exception as exc:
        import traceback
        traceback.print_exc()
        cache.set(_CACHE_KEY,
            {
                'status': 'error',
                'error': str(exc)
            },
            timeout=3600
        )

    finally:
        connection.close()


class MigrationParseView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    """
    POST  — launches a background parse job, returns job_id immediately.
    The browser polls /migration/parse/status/<job_id>/ for results.
    """
    def post(self, request, *args, **kwargs):
        import_type  = request.POST.get('import_type')
        input_method = request.POST.get('input_method')
        drop_first_col = request.POST.get('drop_first_column') == 'true'
        if import_type == 'company':
            drop_first_col = False
        
        if import_type == 'product':
            drop_first_col = False

        # ── Read file / text ──────────────────────────────────────────────
        content = ''
        if input_method == 'file':
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return JsonResponse({'success': False, 'error': 'No file uploaded'})
            content, enc_used = decode_uploaded_file(uploaded_file)
            if enc_used != 'utf-8':
                logger.info(f'File "{uploaded_file.name}" decoded using {enc_used} (legacy encoding).')
        else:
            content = request.POST.get('raw_text', '')

        if not content.strip():
            return JsonResponse({'success': False, 'error': 'No content provided to parse'})

        # ── Resolve tenant ────────────────────────────────────────────────
        tenant_id = request.POST.get('selected_tenant_id')
        if tenant_id and request.user.user_type == 'admin':
            tenant = get_object_or_404(Tenant, id=tenant_id)
        else:
            tenant = request.tenant

        # ── Launch background parse ───────────────────────────────────────
        job_id = str(uuid.uuid4())
        cache.set(f'parse_job_{job_id}', {'status': 'queued', 'progress': 5}, timeout=3600)

        t = threading.Thread(
            target=_run_parse_job,
            args=(job_id, import_type, input_method, content, drop_first_col, tenant.id),
            daemon=True,
            name=f'parse-{job_id[:8]}',
        )
        t.start()

        return JsonResponse({'success': True, 'job_id': job_id, 'status': 'queued'})


class MigrationParseStatusView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    """
    GET /migration/parse/status/<job_id>/
    Returns parse job progress / results from cache.
    """
    def get(self, request, job_id, *args, **kwargs):
        job = cache.get(f'parse_job_{job_id}')
        if not job:
            return JsonResponse({'success': False, 'error': 'Job not found or expired (>1 h).'})
        return JsonResponse({'success': True, **job})

class MigrationImportView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    """
    POST API to complete the transaction-safe import of verified records.
    Launches a background worker thread using Pandas chunking for high performance.
    """
    def post(self, request, *args, **kwargs):
        import_type = request.POST.get('import_type')
        input_method = request.POST.get('input_method')
        drop_first_col = (request.POST.get('drop_first_column') == 'true')
        if import_type == 'company':
            drop_first_col = False
        
        if import_type == 'product':
            drop_first_col = False


        filename = request.POST.get('filename', 'Direct Copy-Paste')
        
        content = ""
        if input_method == 'file':
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return JsonResponse({'success': False, 'error': 'No file uploaded'})
            content, enc_used = decode_uploaded_file(uploaded_file)
            if enc_used != 'utf-8':
                logger.info(f'Import file "{uploaded_file.name}" decoded using {enc_used} (legacy encoding).')
        else:
            content = request.POST.get('raw_text', '')
            
        if not content.strip():
            return JsonResponse({'success': False, 'error': 'No content provided to import'})
            
        # Dynamically resolve tenant based on administrative choice
        tenant_id = request.POST.get('selected_tenant_id')
        if tenant_id and request.user.user_type == 'admin':
            tenant = get_object_or_404(Tenant, id=tenant_id)
        else:
            tenant = request.tenant
        
        try:
            # Create a PENDING migration log entry
            log_entry = MigrationLog.objects.create(
                tenant=tenant,
                import_type=import_type,
                source_name=filename,
                records_count=0,
                imported_by=request.user,
                status='PENDING',
                progress_percent=0,
                metadata={}
            )
            
            # Start background migration processing
            start_background_migration(
                log_id=log_entry.id,
                data_content=content,
                drop_first_col=drop_first_col,
                input_method=input_method
            )
            
            return JsonResponse({
                'success': True,
                'message': 'Migration started successfully in the background!',
                'log_id': log_entry.id
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': f'Failed to launch background migration: {str(e)}'})

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
                elif log.import_type == 'product':
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
