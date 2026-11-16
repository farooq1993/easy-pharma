from django.db import migrations


def drop_ledger_transaction_type_constraints(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    constraint_name = schema_editor.quote_name('chk_transaction_type')
    with schema_editor.connection.cursor() as cursor:
        for table_name in ('easypharma_supplierledger', 'easypharma_customerledger'):
            table = schema_editor.quote_name(table_name)
            cursor.execute(
                f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}'
            )


class Migration(migrations.Migration):

    dependencies = [
        ('easypharma', '0058_drop_supplierledger_chk_constraint'),
    ]

    operations = [
        migrations.RunPython(
            drop_ledger_transaction_type_constraints,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
