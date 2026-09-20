import json
import base64
import os
import sqlite3
from django.views import View
from django.shortcuts import render, redirect
from django.http import JsonResponse, FileResponse, Http404, HttpResponse
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from easypharma.models.stock import StockBatch
from easypharma.models.print_setup import PrintSetup
from easypharma.models.general_setup import GeneralSetup
from datetime import date, timedelta
from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from easypharma.backup_utils import (
    get_backup_directory,
    set_backup_directory,
    take_backup,
    take_safety_backup,
    restore_backup,
    list_backups,
    take_compressed_backup,
    restore_compressed_backup,
    take_tenant_compressed_backup,
    restore_tenant_compressed_backup
)


class UtilityHomeView(View):
    template_name = 'utility/home.html'

    def get(self, request):
        setup, _ = GeneralSetup.objects.get_or_create(tenant=request.tenant)
        return render(request, self.template_name, {
            'setup': setup,
        })

    def post(self, request):
        setup, _ = GeneralSetup.objects.get_or_create(tenant=request.tenant)
        
        # Check if sale_type changed
        old_sale_type = setup.sale_type
        
        # Sale Setup
        setup.sale_type = request.POST.get('sale_type', 'unit')
        setup.default_payment_mode = request.POST.get('default_payment_mode', 'cash')
        setup.require_customer_phone = request.POST.get('require_customer_phone') == 'on'
        setup.print_invoice_after_save = request.POST.get('print_invoice_after_save') == 'on'
        
        # Purchase Setup
        setup.expiry_date_format = request.POST.get('expiry_date_format', 'text')
        try:
            setup.default_tax_rate = float(request.POST.get('default_tax_rate', 18.0))
        except ValueError:
            setup.default_tax_rate = 18.0
        setup.auto_update_selling_price = request.POST.get('auto_update_selling_price') == 'on'
        
        setup.save()
        messages.success(request, "General settings updated successfully!")
        return redirect('utility_home')


class PrintingSetupView(View):
    template_name = 'utility/printing.html'

    def get(self, request):
        setup, _ = PrintSetup.objects.get_or_create(tenant=request.tenant)
        return render(request, self.template_name, {'setup': setup})

    def post(self, request):
        setup, _ = PrintSetup.objects.get_or_create(tenant=request.tenant)

        # Paper settings
        setup.paper_size = request.POST.get('paper_size', 'A4')
        setup.margin_top = int(request.POST.get('margin_top', 10))
        setup.margin_sides = int(request.POST.get('margin_sides', 10))

        # Content toggles
        setup.show_logo = request.POST.get('show_logo') == 'on'
        setup.show_gst_details = request.POST.get('show_gst_details') == 'on'
        setup.show_dl_details = request.POST.get('show_dl_details') == 'on'
        setup.show_customer_signature = request.POST.get('show_customer_signature') == 'on'
        setup.show_pharmacist_signature = request.POST.get('show_pharmacist_signature') == 'on'
        setup.print_single_copy = request.POST.get('print_single_copy') == 'on'

        # Custom text
        setup.custom_header = request.POST.get('custom_header', '').strip() or None
        setup.custom_footer = request.POST.get('custom_footer', '').strip() or None

        # Logo upload (convert to base64)
        logo_file = request.FILES.get('logo_file')
        if logo_file:
            # Validate file type
            if logo_file.content_type in ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp']:
                logo_data = base64.b64encode(logo_file.read()).decode('utf-8')
                setup.logo_base64 = f"data:{logo_file.content_type};base64,{logo_data}"
            else:
                messages.error(request, 'Invalid file type. Please upload PNG, JPG, or GIF.')
                return redirect('printing_setup')

        # Option to clear logo
        if request.POST.get('clear_logo') == 'yes':
            setup.logo_base64 = None

        setup.save()
        messages.success(request, 'Print settings saved successfully!')
        return redirect('printing_setup')


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and (self.request.user.user_type == 'admin' or self.request.user.is_superuser)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        messages.error(self.request, "Access denied. Admin privileges are required.")
        return redirect('home')


class DatabaseBackupView(AdminRequiredMixin, View):
    template_name = 'utility/backup.html'

    def get(self, request):
        db_engine = settings.DATABASES['default']['ENGINE']
        db_name = settings.DATABASES['default']['NAME']
        
        db_size_mb = 0
        db_exists = False
        is_sqlite = 'sqlite3' in db_engine
        
        if is_sqlite:
            if os.path.exists(db_name):
                db_exists = True
                db_size_mb = f"{round(os.path.getsize(db_name) / (1024.0 * 1024.0), 2)} MB"
        else:
            # Query Postgres size
            from django.db import connection
            try:
                connection.cursor()
                db_exists = True
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_size_pretty(pg_database_size(current_database()));")
                    row = cursor.fetchone()
                    if row:
                        db_size_mb = row[0]
            except Exception as e:
                db_exists = False
                db_size_mb = "N/A"
                
        context = {
            'backup_dir': get_backup_directory(),
            'backups': list_backups(),
            'db_engine': db_engine.split('.')[-1],
            'db_path': db_name if is_sqlite else f"{settings.DATABASES['default'].get('HOST', 'localhost')}:{settings.DATABASES['default'].get('PORT', '5432')}/{db_name}",
            'db_size_mb': db_size_mb,
            'db_exists': db_exists,
            'is_sqlite': is_sqlite
        }
        return render(request, self.template_name, context)

    def post(self, request):
        action = request.POST.get('action')
        
        if action == 'save_settings':
            path = request.POST.get('backup_directory', '').strip()
            try:
                set_backup_directory(path)
                messages.success(request, f"Backup directory successfully updated to: {path}")
            except Exception as e:
                messages.error(request, f"Error saving directory: {str(e)}")
                
        elif action == 'take_backup':
            try:
                zip_filename = take_tenant_compressed_backup(request.tenant)
                backup_dir = get_backup_directory()
                file_path = os.path.join(backup_dir, zip_filename)
                
                if os.path.exists(file_path):
                    response = FileResponse(open(file_path, 'rb'), content_type='application/zip')
                    response['Content-Disposition'] = f'attachment; filename="{zip_filename}"'
                    return response
                else:
                    messages.error(request, "Failed to locate the generated backup file.")
            except Exception as e:
                messages.error(request, f"Failed to take backup: {str(e)}")
                
        return redirect('database_backup')


class DownloadBackupView(AdminRequiredMixin, View):
    def get(self, request, filename):
        filename = os.path.basename(filename)
        backup_dir = get_backup_directory()
        file_path = os.path.join(backup_dir, filename)
        
        if os.path.exists(file_path):
            response = FileResponse(open(file_path, 'rb'), content_type='application/octet-stream')
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        else:
            raise Http404("Backup file not found.")


class DeleteBackupView(AdminRequiredMixin, View):
    def post(self, request, filename):
        filename = os.path.basename(filename)
        backup_dir = get_backup_directory()
        file_path = os.path.join(backup_dir, filename)
        
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                messages.success(request, f"Backup '{filename}' deleted successfully.")
            except Exception as e:
                messages.error(request, f"Error deleting file: {str(e)}")
        else:
            messages.error(request, f"Backup file '{filename}' does not exist.")
            
        return redirect('database_backup')


class RestoreBackupView(AdminRequiredMixin, View):
    def post(self, request, filename):
        filename = os.path.basename(filename)
        
        safety_file = None
        try:
            safety_file = take_safety_backup()
        except Exception as e:
            messages.error(request, f"Failed to take safety backup. Restore aborted for security. Error: {str(e)}")
            return redirect('database_backup')
            
        try:
            restore_backup(filename)
            messages.success(
                request, 
                f"Database restored successfully from '{filename}'! "
                f"A safety backup of the previous state was saved as '{safety_file}'."
            )
        except Exception as e:
            messages.error(
                request, 
                f"Critical Error: Failed to restore database: {str(e)}. "
                f"Your database might be in an inconsistent state. Please check or restore another backup."
            )
            
        return redirect('database_backup')


class UploadRestoreBackupView(AdminRequiredMixin, View):
    def post(self, request):
        uploaded_file = request.FILES.get('backup_file')
        if not uploaded_file:
            messages.error(request, "No file uploaded.")
            return redirect('database_backup')
            
        ext = os.path.splitext(uploaded_file.name)[1].lower()
        if ext not in ['.sqlite3', '.dump', '.json', '.zip']:
            messages.error(request, "Invalid file format. Please upload a valid .zip, .sqlite3, .dump, or .json file.")
            return redirect('database_backup')
            
        backup_dir = get_backup_directory()
        os.makedirs(backup_dir, exist_ok=True)
        
        import datetime
        now = datetime.datetime.now()
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        filename = f"easypharma_uploaded_backup_{timestamp}{ext}"
        file_path = os.path.join(backup_dir, filename)
        
        try:
            with open(file_path, 'wb+') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
        except Exception as e:
            messages.error(request, f"Failed to save uploaded file: {str(e)}")
            return redirect('database_backup')
            
        safety_file = None
        try:
            safety_file = take_safety_backup()
        except Exception as e:
            messages.error(request, f"Failed to take safety backup. Restore aborted. Error: {str(e)}")
            if os.path.exists(file_path):
                os.remove(file_path)
            return redirect('database_backup')
            
        try:
            if ext == '.zip':
                restore_tenant_compressed_backup(request.tenant, filename, request.user.id)
                if os.path.exists(file_path):
                    os.remove(file_path)
            else:
                restore_backup(filename)
            messages.success(
                request, 
                f"Database uploaded and restored successfully! "
                f"A safety backup of the previous state was saved as '{safety_file}'."
            )
        except Exception as e:
            messages.error(request, f"Failed to restore from uploaded file: {str(e)}")
            if os.path.exists(file_path):
                try: os.remove(file_path)
                except: pass
            
        return redirect('database_backup')


class BrowseDirectoryView(AdminRequiredMixin, View):
    def get(self, request):
        current_path = request.GET.get('path', '').strip()
        
        if not current_path:
            if os.name == 'nt':
                drives = []
                import string
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:\\"
                    if os.path.exists(drive):
                        drives.append(drive)
                return JsonResponse({
                    'current_path': '',
                    'parent_path': '',
                    'directories': drives,
                    'is_drives': True
                })
            else:
                current_path = '/'
                
        current_path = os.path.abspath(current_path)
        
        if not os.path.exists(current_path) or not os.path.isdir(current_path):
            return JsonResponse({'error': 'Directory does not exist.'}, status=400)
            
        directories = []
        try:
            for item in os.listdir(current_path):
                full_path = os.path.join(current_path, item)
                try:
                    if os.path.isdir(full_path) and not item.startswith('.'):
                        directories.append(item)
                except (PermissionError, OSError):
                    continue
            directories.sort()
        except Exception as e:
            return JsonResponse({'error': f'Cannot read directory: {str(e)}'}, status=400)
            
        parent_path = os.path.dirname(current_path)
        if parent_path == current_path:
            parent_path = ''
            
        return JsonResponse({
            'current_path': current_path,
            'parent_path': parent_path,
            'directories': directories,
            'is_drives': False
        })


class OfflinePageView(View):
    """Serve the PWA offline fallback page — no login required."""

    def get(self, request):
        return render(request, 'offline.html', status=200)


class ServiceWorkerView(View):
    """
    Serve sw.js from the root path (/sw.js) so the Service Worker
    scope covers the entire origin. Must be served with correct MIME
    type and no-cache headers so the browser always gets the latest.
    """

    def get(self, request):
        sw_path = os.path.join(settings.BASE_DIR, 'easypharma', 'static', 'sw.js')
        if not os.path.exists(sw_path):
            raise Http404('Service Worker not found')
        with open(sw_path, 'r', encoding='utf-8') as f:
            content = f.read()
        response = HttpResponse(content, content_type='application/javascript')
        # Ensure browser always checks for updates
        response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response['Service-Worker-Allowed'] = '/'
        return response


class StockMismatchView(LoginRequiredMixin, View):
    template_name = 'utility/stock_mismatch.html'

    def _get_mismatches(self, tenant):
        from easypharma.models.stock import StockBatch
        from easypharma.models.purchase_invoice import PurchaseItem, OpeningStockItem
        from easypharma.models.sales import SaleItem, SalesReturnItem
        from easypharma.models.general_setup import GeneralSetup
        from django.db.models import Sum

        setup = GeneralSetup.objects.filter(tenant=tenant).first()
        sale_type = setup.sale_type if setup else 'unit'

        batches = StockBatch.objects.filter(tenant=tenant).select_related('product').order_by('product__product_name', 'batch_number')

        opening_qs = OpeningStockItem.objects.filter(tenant=tenant).values('product_id', 'batch_number').annotate(total=Sum('quantity'))
        opening_dict = {(item['product_id'], item['batch_number']): item['total'] for item in opening_qs}

        purchases_qs = PurchaseItem.objects.filter(tenant=tenant).values('product_id', 'batch_number').annotate(
            total_qty=Sum('quantity'),
            total_free=Sum('free_quantity')
        )
        purchases_dict = {(item['product_id'], item['batch_number']): (item['total_qty'] or 0) + (item['total_free'] or 0) for item in purchases_qs}

        sales_qs = SaleItem.objects.filter(tenant=tenant).values('product_id', 'batch_number').annotate(total=Sum('quantity'))
        sales_dict = {(item['product_id'], item['batch_number']): item['total'] for item in sales_qs}

        returns_qs = SalesReturnItem.objects.filter(tenant=tenant).values('sale_item__product_id', 'sale_item__batch_number').annotate(total=Sum('returned_quantity'))
        returns_dict = {(item['sale_item__product_id'], item['sale_item__batch_number']): item['total'] for item in returns_qs}

        try:
            from easypharma.models.accounting import ExpiryReturnItem
            expiry_qs = ExpiryReturnItem.objects.filter(tenant=tenant).values('product_id', 'batch_number').annotate(total=Sum('quantity'))
            expiry_dict = {(item['product_id'], item['batch_number']): item['total'] for item in expiry_qs}
        except Exception:
            expiry_dict = {}

        mismatches = []
        for batch in batches:
            key = (batch.product_id, batch.batch_number)
            cf = batch.product.conversion_factor or 1
            
            total_opening = opening_dict.get(key, 0) or 0
            total_purchase = (purchases_dict.get(key, 0) or 0) * cf
            
            raw_sale = sales_dict.get(key, 0) or 0
            total_sale = (raw_sale * cf) if sale_type == 'strip' else raw_sale
            
            total_returns = returns_dict.get(key, 0) or 0
            total_expiry = (expiry_dict.get(key, 0) or 0) * cf

            expected_quantity = total_opening + total_purchase - total_sale + total_returns - total_expiry

            if expected_quantity != batch.current_quantity:
                diff = expected_quantity - batch.current_quantity
                mismatches.append({
                    'batch_id': batch.id,
                    'product_id': batch.product.id,
                    'product_name': batch.product.product_name,
                    'packing': batch.product.product_packing or '',
                    'conversion_factor': cf,
                    'batch_number': batch.batch_number,
                    'expiry_date': batch.expiry_date.strftime('%m/%Y') if batch.expiry_date else '-',
                    'current_quantity': batch.current_quantity,
                    'expected_quantity': expected_quantity,
                    'opening': total_opening,
                    'purchase': total_purchase,
                    'sale': total_sale,
                    'returns': total_returns,
                    'expiry': total_expiry,
                    'diff': diff,
                    'diff_formatted': f"+{diff}" if diff > 0 else f"{diff}",
                })
        return mismatches

    def get(self, request):
        if not (request.user.is_superuser or request.user.user_type in ('admin', 'tenant_owner') or getattr(request.user, 'can_access_utility', False)):
            messages.error(request, "Access denied. You do not have permission to access Utility settings.")
            return redirect('home')

        mismatches = self._get_mismatches(request.tenant)
        return render(request, self.template_name, {
            'mismatches': mismatches,
            'total_mismatches': len(mismatches),
        })

    def post(self, request):
        if not (request.user.is_superuser or request.user.user_type in ('admin', 'tenant_owner') or getattr(request.user, 'can_access_utility', False)):
            return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

        from easypharma.models.stock import StockBatch
        from easypharma.models.purchase_invoice import OpeningStock, OpeningStockItem
        from easypharma.views.reports import invalidate_stock_cache
        from django.utils.timezone import now

        is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.content_type == 'application/json'
        
        data = {}
        if request.content_type == 'application/json':
            try:
                data = json.loads(request.body)
            except Exception:
                pass
        else:
            data = request.POST

        action = data.get('action', 'fix_one')

        if action == 'fix_one':
            batch_id = data.get('batch_id')
            if not batch_id:
                return JsonResponse({'success': False, 'error': 'Batch ID is required'}, status=400)
            
            try:
                batch = StockBatch.objects.get(id=batch_id, tenant=request.tenant)
                mismatches = self._get_mismatches(request.tenant)
                matching = [m for m in mismatches if m['batch_id'] == batch.id]
                expected_qty = matching[0]['expected_quantity'] if matching else batch.current_quantity

                new_quantity_raw = data.get('new_quantity')
                if new_quantity_raw is not None and str(new_quantity_raw).strip() != '':
                    try:
                        new_qty = max(0, int(new_quantity_raw))
                    except ValueError:
                        new_qty = max(0, expected_qty)
                else:
                    new_qty = max(0, expected_qty)

                # Bridge difference in OpeningStock so calculation history aligns with physical stock
                delta = new_qty - expected_qty
                if delta != 0:
                    os_obj = OpeningStock.objects.filter(tenant=request.tenant).order_by('-id').first()
                    if not os_obj:
                        os_obj = OpeningStock.objects.create(
                            tenant=request.tenant,
                            voucher_number=OpeningStock.generate_voucher_number(request.tenant),
                            opening_stock_date=now().date()
                        )
                    
                    os_item = OpeningStockItem.objects.filter(
                        tenant=request.tenant,
                        product=batch.product,
                        batch_number=batch.batch_number
                    ).first()
                    
                    if os_item:
                        new_os_qty = os_item.quantity + delta
                        if new_os_qty < 0:
                            new_os_qty = 0
                        OpeningStockItem.objects.filter(id=os_item.id).update(quantity=new_os_qty)
                    else:
                        if delta > 0:
                            # Create opening stock item for the deficit/adjustment
                            OpeningStockItem.objects.create(
                                tenant=request.tenant,
                                opening_stock=os_obj,
                                product=batch.product,
                                batch_number=batch.batch_number,
                                expiry_date=batch.expiry_date,
                                quantity=delta,
                                purchase_price=batch.purchase_price or 0,
                                mrp=batch.mrp or 0,
                                tax_percentage=0,
                                total_amount=0
                            )

                # Set batch current_quantity
                StockBatch.objects.filter(id=batch.id, tenant=request.tenant).update(
                    current_quantity=new_qty,
                    initial_quantity=max(batch.initial_quantity, new_qty)
                )
                invalidate_stock_cache(request.tenant.id)

                msg = f"Stock for {batch.product.product_name} (Batch {batch.batch_number}) updated to {new_qty}."
                if is_ajax:
                    return JsonResponse({'success': True, 'message': msg, 'new_quantity': new_qty})
                messages.success(request, msg)
                return redirect('stock_mismatch')
            except StockBatch.DoesNotExist:
                return JsonResponse({'success': False, 'error': 'Batch not found'}, status=404)
            except Exception as e:
                return JsonResponse({'success': False, 'error': str(e)}, status=500)

        elif action == 'fix_all':
            try:
                mismatches = self._get_mismatches(request.tenant)
                fixed_count = 0
                os_obj = None

                for item in mismatches:
                    expected = item['expected_quantity']
                    target_qty = max(0, expected)
                    delta = target_qty - expected

                    if delta > 0:
                        if not os_obj:
                            os_obj = OpeningStock.objects.filter(tenant=request.tenant).order_by('-id').first()
                            if not os_obj:
                                os_obj = OpeningStock.objects.create(
                                    tenant=request.tenant,
                                    voucher_number=OpeningStock.generate_voucher_number(request.tenant),
                                    opening_stock_date=now().date()
                                )
                        
                        os_item = OpeningStockItem.objects.filter(
                            tenant=request.tenant,
                            product_id=item['product_id'],
                            batch_number=item['batch_number']
                        ).first()
                        if os_item:
                            OpeningStockItem.objects.filter(id=os_item.id).update(quantity=os_item.quantity + delta)
                        else:
                            OpeningStockItem.objects.create(
                                tenant=request.tenant,
                                opening_stock=os_obj,
                                product_id=item['product_id'],
                                batch_number=item['batch_number'],
                                expiry_date=now().date(),
                                quantity=delta,
                                purchase_price=0,
                                mrp=0,
                                tax_percentage=0,
                                total_amount=0
                            )

                    StockBatch.objects.filter(id=item['batch_id'], tenant=request.tenant).update(
                        current_quantity=target_qty
                    )
                    fixed_count += 1

                invalidate_stock_cache(request.tenant.id)
                msg = f"Successfully reconciled {fixed_count} stock mismatches!"
                if is_ajax:
                    return JsonResponse({'success': True, 'message': msg, 'fixed_count': fixed_count})
                messages.success(request, msg)
                return redirect('stock_mismatch')
            except Exception as e:
                if is_ajax:
                    return JsonResponse({'success': False, 'error': str(e)}, status=500)
                messages.error(request, f"Error fixing stock: {str(e)}")
                return redirect('stock_mismatch')

        return JsonResponse({'success': False, 'error': 'Unknown action'}, status=400)

