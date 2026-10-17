from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('easypharma', '0056_expensecategory_expense'),
    ]

    operations = [
        migrations.AddField(
            model_name='salesreturn',
            name='customer_name',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
    ]
