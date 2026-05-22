import json
from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import TemplateView, View
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.utils import timezone

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
    is_multiline_supplier_layout
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
        return context

class MigrationParseView(LoginRequiredMixin, OrganizationRequiredMixin, View):
    """
    POST API to upload/paste text and parse it into an interactive JSON preview.
    Handles the user's specific request to drop the 1st ID column.
    """
    def post(self, request, *args, **kwargs):
        import_type = request.POST.get('import_type')
        input_method = request.POST.get('input_method')
        drop_first_col = request.POST.get('drop_first_column') == 'true'

        if import_type == 'company':
            drop_first_col = False
        
        content = ""
        if input_method == 'file':
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return JsonResponse({'success': False, 'error': 'No file uploaded'})
            try:
                # Read content as string
                content = uploaded_file.read().decode('utf-8')
                 
            except UnicodeDecodeError as e:
                uploaded_file.seek(0)
                content = uploaded_file.read().decode('latin1')
                print("File decoding error, attempted latin1 fallback:", str(e))
                #return JsonResponse({'success': False, 'error': f'Failed to read file: {str(e)}'})
        else:
            content = request.POST.get('raw_text', '')
            
        if not content.strip():
            return JsonResponse({'success': False, 'error': 'No content provided to parse'})
            
        # Dynamically resolve tenant based on administrative choice
        tenant_id = request.POST.get('selected_tenant_id')
        if tenant_id and request.user.user_type == 'admin':
            tenant = get_object_or_404(Tenant, id=tenant_id)
        else:
            tenant = request.tenant
            
        parsed_data = []
        warnings = []
        
        try:
            # First, tokenize into standard lists of strings (rows)
            # Paste text report could contain custom formatted layouts, handled by specific parsers
            if import_type == 'supplier' and input_method == 'text':
                parsed_raw = parse_suppliers_from_text(content)
                parsed_data = parsed_raw
            else:
                # Delimited parse
                # For supplier imports, we check if it is a multi-line layout BEFORE dropping any columns
                if import_type == 'supplier':
                    if input_method == 'file' and uploaded_file.name.endswith('.csv'):
                        rows = parse_csv_to_rows(content, drop_first_column=False)
                    else:
                        rows = parse_text_lines_to_rows(content, drop_first_column=False)
                        
                    # If it's NOT a multi-line layout and drop_first_col is True, we drop the first column
                    if not is_multiline_supplier_layout(rows) and drop_first_col:
                        rows = [r[1:] for r in rows if len(r) > 0]
                else:
                    if input_method == 'file' and uploaded_file.name.endswith('.csv'):
                        rows = parse_csv_to_rows(content,drop_first_column=drop_first_col)

                    else:
                        rows = parse_text_lines_to_rows(content,drop_first_column=drop_first_col)
                        print("ROWS SAMPLE abc ==> ", rows[:10])
                # else:
                #     if input_method == 'file' and uploaded_file.name.endswith('.csv'):
                #         rows = parse_csv_to_rows(content, drop_first_column=drop_first_col)
                #     else:
                #         rows = parse_text_lines_to_rows(content, drop_first_column=drop_first_col)
                
                # Direct parsing to structured JSON based on model
                if import_type == 'company':
                    print("DROP FIRST => ", drop_first_col)
                    print("ROWS SAMPLE => ", rows[:10])
                    parsed_data = parse_companies(rows)
                    print("PARSED SAMPLE => ", parsed_data[:5])

                elif import_type == 'supplier':
                    parsed_data = parse_suppliers_from_rows(rows)
                elif import_type == 'product':
                    parsed_data = parse_products(rows)
                elif import_type == 'stock':
                    parsed_data = parse_stock_batches(rows)
            
            # Enrich data with DB status check (Existing matches, warning indicators)
            enriched_data = []
            
            for item in parsed_data:
                status = "Ready"
                status_class = "text-success"
                notes = ""
                
                if import_type == 'company':
                    name = item['company_name']
                    exists = DrugCompany.objects.filter(tenant=tenant, company_name__iexact=name).exists()
                    if exists:
                        status = "Exists (Skip/Update)"
                        status_class = "text-warning"
                        notes = "This company is already registered in your database."
                        
                elif import_type == 'supplier':
                    name = item['name']
                    exists = Supplier.objects.filter(tenant=tenant, name__iexact=name).exists()
                    if exists:
                        status = "Exists (Skip/Update)"
                        status_class = "text-warning"
                        notes = "A supplier with this name is already registered."
                        
                elif import_type == 'product':
                    name = item['product_name']
                    # Look up company
                    comp_name = item['company_name']
                    if comp_name:
                        comp_match = DrugCompany.objects.filter(tenant=tenant, company_name__iexact=comp_name).first()
                        if not comp_match:
                            notes = f"Company '{comp_name}' will be automatically created."
                            status = "Ready (Auto-Create Company)"
                            status_class = "text-info"
                            
                    exists = Products.objects.filter(tenant=tenant, product_name__iexact=name).exists()
                    if exists:
                        status = "Exists"
                        status_class = "text-warning"
                        notes = "Product already exists in the catalog."
                        
                elif import_type == 'stock':
                    p_name = item['product_name']
                    batch_num = item['batch_number']
                    
                    # Look up product in catalog
                    prod_match = Products.objects.filter(tenant=tenant, product_name__iexact=p_name).first()
                    if not prod_match:
                        notes = f"Product '{p_name}' not in catalog. Will auto-create product!"
                        status = "Ready (Auto-Create Product)"
                        status_class = "text-info"
                    else:
                        # Check duplicate batch
                        batch_exists = StockBatch.objects.filter(
                            tenant=tenant, 
                            product=prod_match, 
                            batch_number__iexact=batch_num
                        ).exists()
                        if batch_exists:
                            status = "Duplicate Batch"
                            status_class = "text-danger"
                            notes = "This batch number already exists for this product. Importing may result in duplicate stock."
                            
                item['import_status'] = status
                item['import_status_class'] = status_class
                item['notes'] = notes
                enriched_data.append(item)
                
            preview_limit = 100
            preview_data = enriched_data[:preview_limit]
            
            return JsonResponse({
                'success': True,
                'data': preview_data,
                'summary': {
                    'total': len(enriched_data),
                    'preview_count': len(preview_data),
                    'warnings': len([x for x in enriched_data if "Exists" in x['import_status'] or "Duplicate" in x['import_status']]),
                    'is_truncated': len(enriched_data) > preview_limit
                }
            })
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': f'Parsing error: {str(e)}'})

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
        #drop_first_col = request.POST.get('drop_first_column') == 'true'
        filename = request.POST.get('filename', 'Direct Copy-Paste')
        
        content = ""
        if input_method == 'file':
            uploaded_file = request.FILES.get('file')
            if not uploaded_file:
                return JsonResponse({'success': False, 'error': 'No file uploaded'})
            try:
                content = uploaded_file.read().decode('utf-8')
                print("========",content[:500])  # Debug: print first 500 chars of content
            #except Exception as e:
            except UnicodeDecodeError as e:
                uploaded_file.seek(0)
                content = uploaded_file.read().decode( 'latin1')
                print("File decoding error, attempted latin1 fallback:", str(e))
                return JsonResponse({'success': False, 'error': f'Failed to read file: {str(e)}'})
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
