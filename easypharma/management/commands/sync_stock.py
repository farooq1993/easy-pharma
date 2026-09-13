from django.core.management.base import BaseCommand
from easypharma.models.stock import StockBatch
from easypharma.models.purchase_invoice import PurchaseItem, OpeningStockItem
from easypharma.models.sales import SaleItem, SalesReturnItem
from easypharma.models.general_setup import GeneralSetup
from tenants.models import Tenant

class Command(BaseCommand):
    help = 'Recalculates and fixes stock mismatches for all batches based on transaction history'

    def add_arguments(self, parser):
        parser.add_argument('--tenant', type=str, help='Filter by tenant name (e.g., Tuba)')
        parser.add_argument('--fix', action='store_true', help='Apply the calculated stock to the database')

    def handle(self, *args, **options):
        tenant_filter = options['tenant']
        apply_fix = options['fix']

        tenants = Tenant.objects.all()
        if tenant_filter:
            tenants = tenants.filter(name__icontains=tenant_filter)
        
        for tenant in tenants:
            self.stdout.write(self.style.SUCCESS(f"\n--- Processing Tenant: {tenant.name} ---"))
            setup = GeneralSetup.objects.filter(tenant=tenant).first()
            sale_type = setup.sale_type if setup else 'unit'

            batches = StockBatch.objects.filter(tenant=tenant)
            mismatch_count = 0

            for batch in batches:
                product = batch.product
                conversion_factor = product.conversion_factor or 1

                # 1. Opening Stock
                opening_items = OpeningStockItem.objects.filter(
                    tenant=tenant, 
                    product=product, 
                    batch_number=batch.batch_number
                )
                total_opening = sum(item.quantity for item in opening_items)

                # 2. Purchases
                purchase_items = PurchaseItem.objects.filter(
                    tenant=tenant, 
                    product=product, 
                    batch_number=batch.batch_number
                )
                total_purchase = sum(
                    (item.quantity + item.free_quantity) * conversion_factor 
                    for item in purchase_items
                )

                # 3. Sales
                sale_items = SaleItem.objects.filter(
                    tenant=tenant, 
                    product=product, 
                    batch_number=batch.batch_number
                )
                total_sale = 0
                for item in sale_items:
                    if sale_type == 'strip':
                        total_sale += item.quantity * conversion_factor
                    else:
                        total_sale += item.quantity

                # 4. Sales Returns
                return_items = SalesReturnItem.objects.filter(
                    tenant=tenant,
                    sale_item__product=product,
                    sale_item__batch_number=batch.batch_number
                )
                total_returns = sum(item.returned_quantity for item in return_items)

                expected_quantity = total_opening + total_purchase - total_sale + total_returns

                if expected_quantity != batch.current_quantity:
                    mismatch_count += 1
                    self.stdout.write(self.style.WARNING(
                        f"Mismatch! Product: {product.product_name} | Batch: {batch.batch_number}\n"
                        f"  -> DB Stock: {batch.current_quantity}\n"
                        f"  -> Expected: {expected_quantity}\n"
                        f"  (Opening: {total_opening}, Purchase: {total_purchase}, Sale: {total_sale}, Returns: {total_returns})"
                    ))
                    
                    if apply_fix:
                        batch.current_quantity = expected_quantity
                        batch.save()
                        self.stdout.write(self.style.SUCCESS("  -> Fixed!"))

            self.stdout.write(f"Total Mismatches Found: {mismatch_count}")
