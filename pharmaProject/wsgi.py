import os
import django
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharmaProject.settings')

# Initialize Django
django.setup()

# Auto-run migrations on Vercel startup
try:
    print("Checking for database migrations...")
    call_command('migrate', '--noinput')
    print("Migrations completed successfully.")
except Exception as e:
    print(f"Migration error on startup: {e}")

application = get_wsgi_application()
app = application
