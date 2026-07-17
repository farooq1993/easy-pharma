import os
import sqlite3
import datetime
import logging
import subprocess
from django.conf import settings
from django.db import connection, connections
from django.core.management import call_command
from easypharma.models.Items import SystemSetting

logger = logging.getLogger(__name__)

def get_backup_directory():
    """
    Retrieves the user-configured backup directory path.
    Defaults to {BASE_DIR}/backups if not configured.
    """
    try:
        setting = SystemSetting.objects.filter(setting_name='BACKUP_DIRECTORY').first()
        if setting and setting.setting_value.strip():
            return setting.setting_value.strip()
    except Exception as e:
        logger.error(f"Error reading BACKUP_DIRECTORY setting: {e}")
    
    # Default path
    return os.path.join(settings.BASE_DIR, 'backups')

def set_backup_directory(path):
    """
    Saves the user-configured backup directory path.
    """
    path = path.strip()
    if not path:
        raise ValueError("Backup directory path cannot be empty.")
    
    if not os.path.isabs(path):
        raise ValueError("Please provide a valid absolute directory path.")
    
    try:
        os.makedirs(path, exist_ok=True)
        # Test write permission
        temp_file = os.path.join(path, '.write_test')
        with open(temp_file, 'w') as f:
            f.write('test')
        os.remove(temp_file)
    except Exception as e:
        raise OSError(f"Cannot write to the selected path. Error: {str(e)}")
    
    SystemSetting.objects.update_or_create(
        setting_name='BACKUP_DIRECTORY',
        defaults={'setting_value': path, 'description': 'User selected path for database backups'}
    )

def take_backup():
    """
    Creates a database backup. Supports:
    1. SQLite: Binary online backup API.
    2. PostgreSQL: pg_dump utility, or fallback to Django dumpdata JSON serialization.
    """
    backup_dir = get_backup_directory()
    os.makedirs(backup_dir, exist_ok=True)
    
    now = datetime.datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    
    db_engine = settings.DATABASES['default']['ENGINE']
    
    if 'sqlite3' in db_engine:
        filename = f"easypharma_manual_backup_{timestamp}.sqlite3"
        backup_path = os.path.join(backup_dir, filename)
        db_path = settings.DATABASES['default']['NAME']
        
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(backup_path)
        try:
            dst.execute("PRAGMA busy_timeout = 5000")
            src.backup(dst)
        finally:
            dst.close()
            src.close()
            
        return filename
        
    elif 'postgresql' in db_engine or 'postgis' in db_engine:
        # PostgreSQL Dump strategy
        db_config = settings.DATABASES['default']
        db_name = db_config['NAME']
        db_user = db_config.get('USER', '')
        db_password = db_config.get('PASSWORD', '')
        db_host = db_config.get('HOST', 'localhost')
        db_port = db_config.get('PORT', '5432')
        
        filename = f"easypharma_manual_backup_{timestamp}.dump"
        backup_path = os.path.join(backup_dir, filename)
        
        # Try pg_dump binary format (fast and standard)
        try:
            env = os.environ.copy()
            if db_password:
                env['PGPASSWORD'] = db_password
                
            cmd = [
                'pg_dump',
                '-h', db_host,
                '-U', db_user,
                '-p', str(db_port),
                '-d', db_name,
                '-F', 'c',  # Custom archive format (restorable via pg_restore)
                '-b',       # Include large objects
                '-f', backup_path
            ]
            subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return filename
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as e:
            logger.info(f"pg_dump not available or failed ({e}). Falling back to Django JSON dumpdata.")
            
            # Remove failed pg_dump file if created
            if os.path.exists(backup_path):
                try:
                    os.remove(backup_path)
                except:
                    pass
            
            # Fallback JSON dump
            json_filename = f"easypharma_manual_backup_{timestamp}.json"
            json_backup_path = os.path.join(backup_dir, json_filename)
            with open(json_backup_path, 'w', encoding='utf-8') as f:
                call_command('dumpdata', indent=2, stdout=f, exclude=['contenttypes', 'auth.permission', 'sessions', 'admin.logentry'])
            return json_filename
            
    else:
        # Generic DB fallback (dumpdata JSON)
        filename = f"easypharma_manual_backup_{timestamp}.json"
        backup_path = os.path.join(backup_dir, filename)
        with open(backup_path, 'w', encoding='utf-8') as f:
            call_command('dumpdata', indent=2, stdout=f, exclude=['contenttypes', 'auth.permission', 'sessions', 'admin.logentry'])
        return filename

def take_safety_backup():
    """
    Creates a quick safety backup before restoring.
    """
    backup_dir = get_backup_directory()
    os.makedirs(backup_dir, exist_ok=True)
    
    now = datetime.datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    
    db_engine = settings.DATABASES['default']['ENGINE']
    
    if 'sqlite3' in db_engine:
        filename = f"easypharma_safety_backup_before_restore_{timestamp}.sqlite3"
        backup_path = os.path.join(backup_dir, filename)
        db_path = settings.DATABASES['default']['NAME']
        
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(backup_path)
        try:
            dst.execute("PRAGMA busy_timeout = 5000")
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        return filename
        
    elif 'postgresql' in db_engine or 'postgis' in db_engine:
        db_config = settings.DATABASES['default']
        db_name = db_config['NAME']
        db_user = db_config.get('USER', '')
        db_password = db_config.get('PASSWORD', '')
        db_host = db_config.get('HOST', 'localhost')
        db_port = db_config.get('PORT', '5432')
        
        filename = f"easypharma_safety_backup_before_restore_{timestamp}.dump"
        backup_path = os.path.join(backup_dir, filename)
        
        try:
            env = os.environ.copy()
            if db_password:
                env['PGPASSWORD'] = db_password
                
            cmd = [
                'pg_dump',
                '-h', db_host,
                '-U', db_user,
                '-p', str(db_port),
                '-d', db_name,
                '-F', 'c',
                '-b',
                '-f', backup_path
            ]
            subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return filename
        except Exception as e:
            logger.info(f"Safety pg_dump failed ({e}). Falling back to JSON safety backup.")
            if os.path.exists(backup_path):
                try: os.remove(backup_path)
                except: pass
                
            json_filename = f"easypharma_safety_backup_before_restore_{timestamp}.json"
            json_backup_path = os.path.join(backup_dir, json_filename)
            with open(json_backup_path, 'w', encoding='utf-8') as f:
                call_command('dumpdata', indent=2, stdout=f, exclude=['contenttypes', 'auth.permission', 'sessions', 'admin.logentry'])
            return json_filename
            
    else:
        filename = f"easypharma_safety_backup_before_restore_{timestamp}.json"
        backup_path = os.path.join(backup_dir, filename)
        with open(backup_path, 'w', encoding='utf-8') as f:
            call_command('dumpdata', indent=2, stdout=f, exclude=['contenttypes', 'auth.permission', 'sessions', 'admin.logentry'])
        return filename

def restore_backup(filename):
    """
    Restores the database from a backup file.
    Supports .sqlite3, .dump (PostgreSQL custom format), and .json formats.
    """
    backup_dir = get_backup_directory()
    backup_path = os.path.join(backup_dir, filename)
    
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Backup file {filename} not found.")
        
    db_engine = settings.DATABASES['default']['ENGINE']
    
    if filename.endswith('.sqlite3'):
        if 'sqlite3' not in db_engine:
            raise ValueError("Cannot restore a SQLite backup to a non-SQLite database.")
            
        db_path = settings.DATABASES['default']['NAME']
        
        for conn in connections.all():
            conn.close()
            
        src = sqlite3.connect(backup_path)
        dst = sqlite3.connect(db_path)
        try:
            dst.execute("PRAGMA busy_timeout = 10000")
            src.backup(dst)
        finally:
            dst.close()
            src.close()
            
        for conn in connections.all():
            conn.close()
            
    elif filename.endswith('.dump'):
        if 'postgresql' not in db_engine and 'postgis' not in db_engine:
            raise ValueError("Cannot restore PostgreSQL dump file to a non-PostgreSQL database.")
            
        db_config = settings.DATABASES['default']
        db_name = db_config['NAME']
        db_user = db_config.get('USER', '')
        db_password = db_config.get('PASSWORD', '')
        db_host = db_config.get('HOST', 'localhost')
        db_port = db_config.get('PORT', '5432')
        
        for conn in connections.all():
            conn.close()
            
        env = os.environ.copy()
        if db_password:
            env['PGPASSWORD'] = db_password
            
        # Run pg_restore with clean, no-owner, and no-privileges flags
        cmd = [
            'pg_restore',
            '-h', db_host,
            '-U', db_user,
            '-p', str(db_port),
            '-d', db_name,
            '--clean',
            '--no-owner',
            '--no-privileges',
            backup_path
        ]
        subprocess.run(cmd, env=env, check=True)
        
        for conn in connections.all():
            conn.close()
            
    elif filename.endswith('.json'):
        # Restore via Django's native loaddata
        for conn in connections.all():
            conn.close()
            
        call_command('loaddata', backup_path)
        
        for conn in connections.all():
            conn.close()
            
    else:
        raise ValueError("Unsupported backup file format.")

def list_backups():
    """
    Returns a sorted list of backups (newest first) with size and metadata.
    """
    backup_dir = get_backup_directory()
    if not os.path.exists(backup_dir):
        return []
        
    backups = []
    try:
        valid_extensions = ('.sqlite3', '.dump', '.json', '.zip')
        for f in os.listdir(backup_dir):
            if f.startswith('easypharma_') and f.endswith(valid_extensions):
                path = os.path.join(backup_dir, f)
                stat = os.stat(path)
                mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                size_kb = stat.st_size / 1024.0
                
                if 'safety_backup' in f:
                    btype = 'Safety'
                elif 'uploaded_backup' in f:
                    btype = 'Uploaded'
                elif 'auto_backup' in f:
                    btype = 'Auto'
                elif 'compressed_backup' in f:
                    btype = 'Compressed'
                else:
                    btype = 'Manual'
                    
                backups.append({
                    'filename': f,
                    'size_kb': round(size_kb, 1),
                    'size_mb': round(size_kb / 1024.0, 2),
                    'modified_time': mtime,
                    'type': btype
                })
        # Sort newest first
        backups.sort(key=lambda x: x['modified_time'], reverse=True)
    except Exception as e:
        logger.error(f"Error listing backups: {e}")
        
    return backups

import zipfile

def take_compressed_backup():
    """
    Creates a database backup, compresses it into a ZIP file,
    and deletes the raw uncompressed backup file.
    """
    # 1. Take a standard database backup
    filename = take_backup()
    backup_dir = get_backup_directory()
    file_path = os.path.join(backup_dir, filename)
    
    # 2. Define zip filename and path
    now = datetime.datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    zip_filename = f"easypharma_compressed_backup_{timestamp}.zip"
    zip_path = os.path.join(backup_dir, zip_filename)
    
    try:
        # Create ZIP archive
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(file_path, arcname=filename)
        
        # 3. Clean up the uncompressed file from the server
        if os.path.exists(file_path):
            os.remove(file_path)
            
        return zip_filename
    except Exception as e:
        if os.path.exists(zip_path):
            try: os.remove(zip_path)
            except: pass
        raise e

def restore_compressed_backup(zip_filename):
    """
    Extracts the database file from a ZIP backup and restores it.
    Cleans up the extracted file afterwards.
    """
    backup_dir = get_backup_directory()
    zip_path = os.path.join(backup_dir, zip_filename)
    
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Backup zip file {zip_filename} not found.")
        
    extracted_filename = None
    try:
        # Extract the ZIP contents
        with zipfile.ZipFile(zip_path, 'r') as zip_file:
            namelist = zip_file.namelist()
            if not namelist:
                raise ValueError("The uploaded ZIP file is empty.")
            
            # Find a valid database file in the zip
            db_files = [f for f in namelist if f.endswith(('.sqlite3', '.dump', '.json'))]
            if not db_files:
                raise ValueError("No valid database file found in the ZIP archive (.sqlite3, .dump, or .json).")
            
            extracted_filename = db_files[0]
            zip_file.extract(extracted_filename, backup_dir)
            
        # Restore from the extracted uncompressed file
        restore_backup(extracted_filename)
    finally:
        # Clean up the extracted uncompressed file
        if extracted_filename:
            extracted_path = os.path.join(backup_dir, extracted_filename)
            if os.path.exists(extracted_path):
                try: os.remove(extracted_path)
                except: pass

import json
from django.apps import apps
from django.core import serializers
from django.db import transaction, connection
from easypharma.models.accounts import User

def export_tenant_data_json(tenant):
    """
    Serializes all database records belonging to a specific tenant.
    """
    serialized_data = []
    # Loop through all models registered in the Django project
    for model in apps.get_models():
        # Check if the model has a 'tenant' field/foreign key relation
        if hasattr(model, 'tenant') or any(field.name == 'tenant' for field in model._meta.fields):
            queryset = model.objects.filter(tenant=tenant)
            data_list = serializers.serialize('python', queryset)
            serialized_data.extend(data_list)
    return json.dumps(serialized_data, default=str)

def restore_tenant_data_json(tenant, json_data, current_user_id):
    """
    Deletes existing tenant-specific data and restores from serialized JSON objects.
    """
    objects = json.loads(json_data)
    
    db_engine = settings.DATABASES['default']['ENGINE']
    is_sqlite = 'sqlite3' in db_engine
    
    with transaction.atomic():
        if is_sqlite:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA foreign_keys = OFF;")
                
        try:
            # 1. Delete all existing records for this tenant across all models
            # We exclude the currently logged-in user to prevent auth session crash
            for model in apps.get_models():
                if hasattr(model, 'tenant') or any(field.name == 'tenant' for field in model._meta.fields):
                    if model == User:
                        model.objects.filter(tenant=tenant).exclude(id=current_user_id).delete()
                    else:
                        model.objects.filter(tenant=tenant).delete()
                        
            # 2. Deserialize and save imported records
            deserialized_objects = serializers.deserialize('python', objects)
            for obj in deserialized_objects:
                # Security: verify object belongs to the current tenant
                if hasattr(obj.object, 'tenant') and obj.object.tenant_id != tenant.id:
                    continue
                # Save object (does update_or_create behavior for the logged-in user PK)
                obj.save()
                
        finally:
            if is_sqlite:
                with connection.cursor() as cursor:
                    cursor.execute("PRAGMA foreign_keys = ON;")

def take_tenant_compressed_backup(tenant):
    """
    Generates a tenant-specific data dump, compresses it to ZIP, and cleans up JSON.
    """
    backup_dir = get_backup_directory()
    os.makedirs(backup_dir, exist_ok=True)
    
    now = datetime.datetime.now()
    timestamp = now.strftime('%Y%m%d_%H%M%S')
    
    # 1. Serialize tenant data to JSON string
    json_data = export_tenant_data_json(tenant)
    
    # 2. Define file paths
    json_filename = f"easypharma_tenant_data_{tenant.subdomain}_{timestamp}.json"
    json_path = os.path.join(backup_dir, json_filename)
    
    zip_filename = f"easypharma_tenant_backup_{tenant.subdomain}_{timestamp}.zip"
    zip_path = os.path.join(backup_dir, zip_filename)
    
    try:
        # Write uncompressed JSON
        with open(json_path, 'w', encoding='utf-8') as f:
            f.write(json_data)
            
        # Compress to ZIP
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.write(json_path, arcname=json_filename)
            
        # Clean up JSON from server
        if os.path.exists(json_path):
            os.remove(json_path)
            
        return zip_filename
    except Exception as e:
        if os.path.exists(json_path):
            try: os.remove(json_path)
            except: pass
        if os.path.exists(zip_path):
            try: os.remove(zip_path)
            except: pass
        raise e

def restore_tenant_compressed_backup(tenant, zip_filename, current_user_id):
    """
    Extracts the JSON payload from a ZIP file and restores the tenant's database records.
    """
    backup_dir = get_backup_directory()
    zip_path = os.path.join(backup_dir, zip_filename)
    
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Backup zip file {zip_filename} not found.")
        
    extracted_filename = None
    try:
        # Extract the ZIP contents
        with zipfile.ZipFile(zip_path, 'r') as zip_file:
            namelist = zip_file.namelist()
            if not namelist:
                raise ValueError("The uploaded ZIP file is empty.")
            
            # Find a valid JSON file in the ZIP
            json_files = [f for f in namelist if f.endswith('.json')]
            if not json_files:
                raise ValueError("No valid JSON database file found in the ZIP archive.")
            
            extracted_filename = json_files[0]
            zip_file.extract(extracted_filename, backup_dir)
            
        # Read the JSON database data
        extracted_path = os.path.join(backup_dir, extracted_filename)
        with open(extracted_path, 'r', encoding='utf-8') as f:
            json_data = f.read()
            
        # Restore tenant-specific objects
        restore_tenant_data_json(tenant, json_data, current_user_id)
        
    finally:
        # Clean up the extracted uncompressed JSON file
        if extracted_filename:
            extracted_path = os.path.join(backup_dir, extracted_filename)
            if os.path.exists(extracted_path):
                try: os.remove(extracted_path)
                except: pass

