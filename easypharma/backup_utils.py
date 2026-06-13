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
        valid_extensions = ('.sqlite3', '.dump', '.json')
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
