import os
import django
from django.core.wsgi import get_wsgi_application
from django.core.management import call_command

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pharmaProject.settings')

# Initialize Django
django.setup()

# Auto-run tasks on Vercel startup
try:
    print("Running migrations...")
    call_command('migrate', '--noinput')
    
    # Create Default Admin User
    from easypharma.models import User
    if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser(username='admin', password='admin123')
        print("Default admin user created: admin / admin123")
    else:
        print("Admin user already exists.")
        
except Exception as e:
    print(f"Startup error: {e}")

application = get_wsgi_application()
app = application
