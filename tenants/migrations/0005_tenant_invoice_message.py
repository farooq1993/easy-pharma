from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tenants', '0004_tenant_access_key'),
    ]

    operations = [
        migrations.AddField(
            model_name='tenant',
            name='invoice_message',
            field=models.TextField(blank=True, null=True),
        ),
    ]
