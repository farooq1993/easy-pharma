import os
import django
from django.core.management import call_command
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharmaProject.settings')

django.setup()

# Auto-run migrations on startup.
# If migrations cannot be applied, the startup will fail and the app will not run.
try:
    call_command('migrate', '--noinput')
except Exception as exc:
    raise RuntimeError('Automatic startup migration failed') from exc

application = get_wsgi_application()
app = application
