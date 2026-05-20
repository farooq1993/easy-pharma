import threading
import io
import json
import traceback
import pandas as pd
from django.db import transaction
from django.utils import timezone
from tenants.models import Tenant
from easypharma.models.Items import Products, DrugCompany, ProductType
from easypharma.models.purchase_invoice import Supplier
from easypharma.models.stock import StockBatch
from dataMigration.models import MigrationLog
from dataMigration.parsers import (
    parse_csv_to_rows,
    parse_text_lines_to_rows,
    parse_companies,
    parse_suppliers_from_rows,
    parse_suppliers_from_text,
    parse_products,
    parse_stock_batches
)

class MigrationBackgroundWorker(threading.Thread):
    def __init__(self, log_id, data_content, drop_first_col=False, input_method='text'):
        super().__init__()
        self.log_id = log_id
        self.data_content = data_content
        self.drop_first_col = drop_first_col
        self.input_method = input_method
        
    def run(self):
        # Fetch the migration log entry
        try:
            log_entry = MigrationLog.objects.get(id=self.log_id)
        except MigrationLog.DoesNotExist:
            return
            
        tenant = log_entry.tenant
        import_type = log_entry.import_type
        
        log_entry.status = 'PROCESSING'
        log_entry.progress_percent = 5
        log_entry.save()
        
        created_primary_keys = []
        created_dependency_keys = {}
        
        try:
            # Step 1: Use Pandas to read data in chunks efficiently
            chunk_size = 200  # Process 200 rows at a time
            
            # Convert raw text content to an input stream
            data_stream = io.StringIO(self.data_content.strip())
            
            # Determine how to read the data using pandas
            # If supplier master copy-paste text report, it uses custom multiline key-value parsing
            if import_type == 'supplier' and self.input_method == 'text':
                # Custom stateful multiline block parser
                suppliers = parse_suppliers_from_text(self.data_content)
                total_rows = len(suppliers)
                log_entry.progress_percent = 15
                log_entry.save()
                
                # Process suppliers in chunks manually
                for i in range(0, total_rows, chunk_size):
                    chunk = suppliers[i:i + chunk_size]
                    
                    with transaction.atomic():
                        for item in chunk:
                            obj, created = Supplier.objects.get_or_create(
                                tenant=tenant,
                                name=item['name'].upper(),
                                defaults={
                                    'phone': item['phone'] or '0000000000',
                                    'address': item['address'],
                                    'email': item['email'],
                                    'gst_number': item['gst'],
                                    'dl_number': item['dl']
                                }
                            )
                            if created:
                                created_primary_keys.append(obj.id)
                                
                    # Update progress
                    progress = int(15 + (i + len(chunk)) / total_rows * 80)
                    log_entry.progress_percent = min(progress, 95)
                    log_entry.records_count = len(created_primary_keys)
                    log_entry.save()
                    
            else:
                # 1. Parse the entire content into uniform lists using robust custom tokenizers
                # This makes us 100% immune to pandas.errors.ParserError due to non-uniform dot-matrix layouts.
                if self.input_method == 'file' and self.data_content.startswith(('"', 'Code', 'Product', 'Name')):
                    rows = parse_csv_to_rows(self.data_content, drop_first_column=self.drop_first_col)
                else:
                    rows = parse_text_lines_to_rows(self.data_content, drop_first_column=self.drop_first_col)
                
                # 2. Use Pandas to clean and load the entire dataset efficiently
                df = pd.DataFrame(rows)
                df = df.fillna('').astype(str)
                cleaned_rows = df.values.tolist()
                
                # Filter out report level header and footer lines
                filtered_rows = []
                for r in cleaned_rows:
                    row_str = " ".join(r).strip()
                    if not row_str or any(x in row_str for x in ["Page No", "Printed on", "Products Typewise"]):
                        continue
                    filtered_rows.append(r)
                
                # 3. Parse the entire Clean dataset to preserve state across chunk boundaries
                all_parsed_items = []
                if import_type == 'company':
                    all_parsed_items = parse_companies(filtered_rows)
                elif import_type == 'supplier':
                    all_parsed_items = parse_suppliers_from_rows(filtered_rows)
                elif import_type == 'product':
                    all_parsed_items = parse_products(filtered_rows)
                elif import_type == 'stock':
                    all_parsed_items = parse_stock_batches(filtered_rows)
                    
                total_items = len(all_parsed_items)
                if total_items == 0:
                    total_items = 1
                
                # 4. Commit parsed items to database in chunked atomic transactions
                for i in range(0, len(all_parsed_items), chunk_size):
                    chunk_items = all_parsed_items[i : i + chunk_size]
                    
                    with transaction.atomic():
                        if import_type == 'company':
                            for item in chunk_items:
                                obj, created = DrugCompany.objects.get_or_create(
                                    tenant=tenant,
                                    company_name=item['company_name'].upper(),
                                    defaults={'sht_name': item['sht_name'].upper()}
                                )
                                if created:
                                    created_primary_keys.append(obj.id)
                                    
                        elif import_type == 'supplier':
                            for item in chunk_items:
                                obj, created = Supplier.objects.get_or_create(
                                    tenant=tenant,
                                    name=item['name'].upper(),
                                    defaults={
                                        'phone': item['phone'] or '0000000000',
                                        'address': item['address'],
                                        'email': item['email'],
                                        'gst_number': item['gst'],
                                        'dl_number': item['dl']
                                    }
                                )
                                if created:
                                    created_primary_keys.append(obj.id)
                                    
                        elif import_type == 'product':
                            for item in chunk_items:
                                comp_obj = None
                                comp_name = item['company_name']
                                if comp_name:
                                    comp_obj, comp_created = DrugCompany.objects.get_or_create(
                                        tenant=tenant,
                                        company_name=comp_name.upper(),
                                        defaults={'sht_name': comp_name[:6].upper()}
                                    )
                                    if comp_created:
                                        created_dependency_keys.setdefault('DrugCompany', []).append(comp_obj.id)
                                
                                type_obj = None
                                type_name = item['product_type']
                                if type_name:
                                    type_obj, type_created = ProductType.objects.get_or_create(
                                        tenant=tenant,
                                        name=type_name.upper()
                                    )
                                    if type_created:
                                        created_dependency_keys.setdefault('ProductType', []).append(type_obj.id)
                                        
                                obj, created = Products.objects.get_or_create(
                                    tenant=tenant,
                                    product_name=item['product_name'].upper(),
                                    defaults={
                                        'product_packing': item['product_packing'],
                                        'compny_name': comp_obj,
                                        'product_type': type_obj,
                                        'product_hsn_code': item['hsn_code'] or '3004',
                                        'conversion_factor': item['conversion_factor'] or 1
                                    }
                                )
                                if created:
                                    created_primary_keys.append(obj.id)
                                    
                        elif import_type == 'stock':
                            for item in chunk_items:
                                p_name = item['product_name']
                                comp_name = item['company_name']
                                
                                comp_obj = None
                                if comp_name:
                                    comp_obj, comp_created = DrugCompany.objects.get_or_create(
                                        tenant=tenant,
                                        company_name=comp_name.upper(),
                                        defaults={'sht_name': comp_name[:6].upper()}
                                    )
                                    if comp_created:
                                        created_dependency_keys.setdefault('DrugCompany', []).append(comp_obj.id)
                                        
                                type_obj = None
                                type_name = item['product_type']
                                if type_name:
                                    type_obj, type_created = ProductType.objects.get_or_create(
                                        tenant=tenant,
                                        name=type_name.upper()
                                    )
                                    if type_created:
                                        created_dependency_keys.setdefault('ProductType', []).append(type_obj.id)
                                
                                prod_obj, prod_created = Products.objects.get_or_create(
                                    tenant=tenant,
                                    product_name=p_name.upper(),
                                    defaults={
                                        'product_packing': f"{item['conversion_factor']} TAB",
                                        'compny_name': comp_obj,
                                        'product_type': type_obj,
                                        'product_hsn_code': '3004',
                                        'conversion_factor': item['conversion_factor'] or 1
                                    }
                                )
                                if prod_created:
                                    created_dependency_keys.setdefault('Products', []).append(prod_obj.id)
                                    
                                exp_date_str = item['expiry_date']
                                if not exp_date_str:
                                    exp_date_str = timezone.now().date().strftime('%Y-%m-%d')
                                    
                                mrp = float(item['mrp']) if item['mrp'] else 0.0
                                purchase_price = mrp * 0.8
                                sale_price = mrp
                                
                                stock_obj = StockBatch.objects.create(
                                    tenant=tenant,
                                    product=prod_obj,
                                    batch_number=item['batch_number'].upper(),
                                    expiry_date=exp_date_str,
                                    purchase_price=purchase_price,
                                    mrp=mrp,
                                    sale_price=sale_price,
                                    initial_quantity=item['quantity'] or 0,
                                    current_quantity=item['quantity'] or 0
                                )
                                created_primary_keys.append(stock_obj.id)
                                
                    # Update progress percent and running counts
                    processed_items = i + len(chunk_items)
                    progress = int(10 + (processed_items / total_items) * 85)
                    log_entry.progress_percent = min(progress, 99)
                    log_entry.records_count = len(created_primary_keys)
                    log_entry.save()
            
            # Finished successfully!
            log_entry.status = 'SUCCESS'
            log_entry.progress_percent = 100
            log_entry.metadata = {
                'created_ids': created_primary_keys,
                'created_dependencies': created_dependency_keys
            }
            log_entry.save()
            
        except Exception as e:
            traceback.print_exc()
            log_entry.status = 'FAILED'
            log_entry.error_message = str(e)
            log_entry.progress_percent = 100
            log_entry.save()

def start_background_migration(log_id, data_content, drop_first_col=False, input_method='text'):
    worker = MigrationBackgroundWorker(log_id, data_content, drop_first_col, input_method)
    worker.daemon = True
    worker.start()
