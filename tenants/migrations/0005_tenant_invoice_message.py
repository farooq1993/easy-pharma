from django.db import migrations, models, connection


def add_invoice_message_field(apps, schema_editor):
    """Safely add invoice_message field if it doesn't already exist."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'tenants_tenant' 
                AND column_name = 'invoice_message'
            );
        """)
        column_exists = cursor.fetchone()[0]
    
    if not column_exists:
        # Column doesn't exist, add it
        schema_editor.add_field(
            apps.get_model('tenants', 'Tenant'),
            models.TextField(blank=True, null=True, name='invoice_message')
        )


def reverse_add_invoice_message(apps, schema_editor):
    """Reverse: remove invoice_message field if it exists."""
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.columns 
                WHERE table_name = 'tenants_tenant' 
                AND column_name = 'invoice_message'
            );
        """)
        column_exists = cursor.fetchone()[0]
    
    if column_exists:
        schema_editor.remove_field(
            apps.get_model('tenants', 'Tenant'),
            'invoice_message'
        )


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0004_tenant_access_key'),
    ]

    operations = [
        migrations.RunPython(add_invoice_message_field, reverse_add_invoice_message),
    ]
