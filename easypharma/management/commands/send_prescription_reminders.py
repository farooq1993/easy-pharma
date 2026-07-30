import threading
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from tenants.models import Tenant
from easypharma.models.sales import PrescriptionReminder
from easypharma.services.notifications import send_whatsapp_message

class MockRequest:
    def __init__(self, tenant):
        self.tenant = tenant

class Command(BaseCommand):
    help = 'Send prescription reminders automatically to patients via WhatsApp'

    def handle(self, *args, **kwargs):
        self.stdout.write("--- Starting Automated Prescription Reminders Task ---")
        
        today = timezone.now().date()
        active_tenants = Tenant.objects.filter(is_active=True)
        
        if not active_tenants.exists():
            self.stdout.write("No active tenants found.")
            return

        current_thread = threading.current_thread()
        original_request = getattr(current_thread, 'request', None)

        for tenant in active_tenants:
            self.stdout.write(f"\nProcessing reminders for Pharmacy: {tenant.pharmacy_name} (Subdomain: {tenant.subdomain})")
            
            # Switch database context using mock request on the thread
            current_thread.request = MockRequest(tenant)
            
            # Determine database name if running on multi-database production (Railway)
            db_alias = 'default'
            if getattr(settings, 'ON_RAILWAY', False):
                db_alias = tenant.database_name
                self.stdout.write(f"Using tenant database: {db_alias}")
            
            try:
                # Find all pending reminders due today or past due
                reminders = PrescriptionReminder.objects.using(db_alias).filter(
                    tenant=tenant,
                    reminder_date__lte=today,
                    status='pending'
                )
                
                count = reminders.count()
                self.stdout.write(f"Found {count} pending reminders.")
                
                for reminder in reminders:
                    if not reminder.patient_phone:
                        self.stdout.write(self.style.WARNING(
                            f"Skipping reminder ID {reminder.id} for {reminder.patient_name}: No phone number stored."
                        ))
                        # Update status to failed so we don't block other tasks, but note the reason
                        reminder.status = 'failed'
                        reminder.notes = f"{reminder.notes or ''} [Failed: No phone number stored]".strip()
                        reminder.save(using=db_alias)
                        continue

                    # Construct the message template
                    pharmacy_name = tenant.pharmacy_name or "EASY PHARMA"
                    msg = (
                        f"*{pharmacy_name.upper()} - PRESCRIPTION REMINDER*\n\n"
                        f"Hello {reminder.patient_name},\n"
                        f"This is a friendly reminder to refill your prescription medicines.\n"
                        f"Please visit our pharmacy or contact us to restock.\n\n"
                        f"Stay Healthy!"
                    )
                    
                    self.stdout.write(f"Sending message to {reminder.patient_name} ({reminder.patient_phone})...")
                    
                    # Call notification service
                    success, error_msg = send_whatsapp_message(reminder.patient_phone, msg, tenant=tenant)
                    
                    if success:
                        reminder.status = 'sent'
                        reminder.sent_at = timezone.now()
                        reminder.save(using=db_alias)
                        self.stdout.write(self.style.SUCCESS(f"Successfully sent reminder to {reminder.patient_name}"))
                    else:
                        reminder.status = 'failed'
                        reminder.notes = f"{reminder.notes or ''} [Auto-send failed: {error_msg}]".strip()
                        reminder.save(using=db_alias)
                        self.stdout.write(self.style.ERROR(
                            f"Failed to send reminder to {reminder.patient_name}: {error_msg}"
                        ))
            
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing tenant {tenant.pharmacy_name}: {e}"))
            
            finally:
                # Clear request context to avoid leaking
                if hasattr(current_thread, 'request'):
                    del current_thread.request
        
        # Restore original thread context if any
        if original_request:
            current_thread.request = original_request
            
        self.stdout.write("\n--- Automated Prescription Reminders Task Completed ---")
