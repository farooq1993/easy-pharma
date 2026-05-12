from django.views import View
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib import messages
from easypharma.models.Items import Products
from easypharma.models.sales import SaleInvoice, SaleItem, Customer
from django.db import transaction
import json
from datetime import datetime

from easypharma.models.Items import Products, ProductTax

class POSView(View):
    template_name = 'sales/pos.html'

    def get(self, request):
        products = Products.objects.filter(tenant=request.tenant)
        customers = Customer.objects.filter(tenant=request.tenant)
        product_taxes = ProductTax.objects.filter(tenant=request.tenant)
        return render(request, self.template_name, {
            'products': products,
            'customers': customers,
            'product_taxes': product_taxes
        })

    def post(self, request):
        try:
            if not request.tenant:
                return JsonResponse({'success': False, 'error': 'No Pharmacy detected! Please assign a Pharmacy (Tenant) to your user account in Admin.'})
            
            data = json.loads(request.body)
            tenant_id = request.tenant.id
            from easypharma.models.stock import StockBatch
            
            with transaction.atomic():
                # Generate a unique invoice number
                count = SaleInvoice.objects.filter(tenant=request.tenant).count()
                invoice_no = f"INV-{tenant_id}-{count + 1}"
                
                # Create Sale Invoice
                invoice = SaleInvoice.objects.create(
                    tenant=request.tenant,
                    user=request.user,
                    invoice_number=invoice_no,
                    patient_name=data.get('patient_name'),
                    patient_phone=data.get('patient_phone'),
                    doctor_name=data.get('doctor_name'),
                    sub_total=data['sub_total'],
                    tax_amount=data['tax_amount'],
                    discount_amount=data['discount_amount'],
                    total_amount=data['total_amount'],
                    payment_mode=data['payment_mode']
                )
                
                # Create Sale Items & Deduct Stock
                for item in data.get('items', []):
                    product = Products.objects.get(id=item['product_id'], tenant=request.tenant)
                    
                    # Deduct from first available batch (FIFO)
                    batch = StockBatch.objects.filter(
                        tenant=request.tenant, 
                        product=product,
                        current_quantity__gt=0
                    ).order_by('expiry_date').first()
                    
                    if not batch:
                        raise Exception(f"No stock available for {product.product_name}")
                        
                    SaleItem.objects.create(
                        tenant=request.tenant,
                        sale_invoice=invoice,
                        product=product,
                        batch_number=batch.batch_number,
                        expiry_date=batch.expiry_date,
                        quantity=item['quantity'],
                        unit_price=item['price'],
                        total_amount=item['total']
                    )
                    
                    # Update stock batch
                    batch.current_quantity -= item['quantity']
                    if batch.current_quantity < 0:
                        raise Exception(f"Insufficient stock for {product.product_name}")
                    batch.save()
                
                return JsonResponse({
                    'success': True, 
                    'invoice_id': invoice.id, 
                    'invoice_number': invoice.invoice_number
                })
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

class PrintInvoiceView(View):
    template_name = 'sales/print_invoice.html'

    def get(self, request, invoice_id):
        from django.shortcuts import get_object_or_404
        invoice = get_object_or_404(SaleInvoice, id=invoice_id)
        if not invoice.tenant and request.tenant:
            # Fallback for old bills created without tenant (for debug/dev)
            invoice.tenant = request.tenant
        return render(request, self.template_name, {'invoice': invoice})

class SaleListView(View):
    template_name = 'sales/list.html'

    def get(self, request):
        invoices = SaleInvoice.objects.filter(tenant=request.tenant).order_by('-created_at')
        return render(request, self.template_name, {'invoices': invoices})

    def delete(self, request, invoice_id):
        try:
            with transaction.atomic():
                invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                
                # REVERT STOCK: Add back the sold quantities
                for item in invoice.items.all():
                    from easypharma.models.stock import StockBatch
                    # Find the most recent batch for this product (simplified logic)
                    batch = StockBatch.objects.filter(
                        tenant=request.tenant, 
                        product=item.product,
                        batch_number=item.batch_number
                    ).first()
                    
                    if batch:
                        batch.current_quantity += item.quantity
                        batch.save()
                
                invoice.delete()
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

class ProductSearchAPI(View):
    def get(self, request):
        query = request.GET.get('q', '')
        from easypharma.models.stock import StockBatch
        
        # Find products that have stock batches available
        # Or just products that match the name
        products = Products.objects.filter(
            tenant=request.tenant,
            product_name__icontains=query
        ).select_related('product_tax').prefetch_related('batches')[:10]
        
        data = []
        for p in products:
            batch = p.batches.filter(current_quantity__gt=0).order_by('expiry_date').first()
            
            # Ensure price is per individual unit
            unit_price = 0
            if batch:
                unit_price = float(batch.sale_price)
                # If the stored sale_price seems to be a pack price (i.e. > mrp/factor), adjust it
                # or just always calculate from batch.mrp / p.conversion_factor for safety
                if p.conversion_factor > 1:
                    # In retail, we usually sell at MRP/factor
                    unit_price = float(batch.mrp) / p.conversion_factor
            
            data.append({
                'id': p.id,
                'name': p.product_name,
                'packing': p.product_packing,
                'price': unit_price,
                'stock': batch.current_quantity if batch else 0,
                'batch_no': batch.batch_number if batch else 'N/A',
                'expiry': batch.expiry_date.strftime('%m/%y') if batch else 'N/A',
                'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                'conversion_factor': p.conversion_factor
            })
            
        return JsonResponse(data, safe=False)
