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
        today = date.today()
        expiry_6_months = today + timedelta(days=180)
        expiring_batches = StockBatch.objects.filter(
            tenant=request.tenant,
            expiry_date__lte=expiry_6_months,
            current_quantity__gt=0
        ).select_related('product').order_by('expiry_date')

        return render(request, self.template_name, {
            'expiring_batches': expiring_batches,
        })


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

