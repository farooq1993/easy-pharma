import os
import logging
import django
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application
from django.db import ProgrammingError

logger = logging.getLogger('easypharma')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharmaProject.settings')

django.setup()

# Auto-run migrations on startup.
# Gracefully handle idempotent migration failures (e.g., column already exists).
try:
    call_command('migrate', '--noinput')
    logger.info('✓ Database migrations completed successfully')
except ProgrammingError as exc:
    error_msg = str(exc)
    # Check for common idempotent errors that don't block startup
    if 'already exists' in error_msg or 'duplicate key' in error_msg:
        logger.warning(f'⚠ Migration warning (non-blocking): {error_msg}')
        logger.info('App will continue running with potential schema mismatch')
    else:
        logger.error(f'✗ Critical migration error: {error_msg}')
        raise RuntimeError('Automatic startup migration failed - critical error') from exc
except Exception as exc:
    logger.error(f'✗ Unexpected migration error: {type(exc).__name__}: {exc}')
    raise RuntimeError('Automatic startup migration failed') from exc

application = get_wsgi_application()
app = application
