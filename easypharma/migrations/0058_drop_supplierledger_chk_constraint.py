from django.db import migrations

def drop_chk_constraints(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            # 1. Drop chk_transaction_type on easypharma_supplierledger
            cursor.execute("""
                ALTER TABLE easypharma_supplierledger DROP CONSTRAINT IF EXISTS chk_transaction_type;
            """)
            # 2. Also drop any auto-generated check constraints on transaction_type on supplierledger
            cursor.execute("""
                DO $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (
                        SELECT conname 
                        FROM pg_constraint 
                        WHERE conrelid = 'easypharma_supplierledger'::regclass 
                          AND contype = 'c' 
                          AND (conname LIKE '%transaction_type%' OR conname = 'chk_transaction_type')
                    ) LOOP
                        EXECUTE 'ALTER TABLE easypharma_supplierledger DROP CONSTRAINT IF EXISTS ' || quote_ident(r.conname);
                    END LOOP;
                END $$;
            """)
            # 3. Same safety for easypharma_customerledger
            cursor.execute("""
                DO $$
                DECLARE
                    r RECORD;
                BEGIN
                    FOR r IN (
                        SELECT conname 
                        FROM pg_constraint 
                        WHERE conrelid = 'easypharma_customerledger'::regclass 
                          AND contype = 'c' 
                          AND (conname LIKE '%transaction_type%' OR conname = 'chk_transaction_type')
                    ) LOOP
                        EXECUTE 'ALTER TABLE easypharma_customerledger DROP CONSTRAINT IF EXISTS ' || quote_ident(r.conname);
                    END LOOP;
                END $$;
            """)

def reverse_chk(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('easypharma', '0057_salesreturn_customer_name'),
    ]

    operations = [
        migrations.RunPython(drop_chk_constraints, reverse_code=reverse_chk),
    ]
