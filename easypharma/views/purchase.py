from django.views import View
from django.shortcuts import render, redirect
from django.http import JsonResponse
from easypharma.models.Items import Products
from easypharma.models.purchase_invoice import Supplier, PurchaseInvoice, PurchaseItem
from easypharma.models.stock import StockBatch
from django.db import transaction
import json

class PurchaseEntryView(View):
    template_name = 'purchase/entry.html'

    def get(self, request, invoice_id=None):
        suppliers = Supplier.objects.filter(tenant=request.tenant)
        products = Products.objects.filter(tenant=request.tenant)
        from easypharma.models.Items import ProductTax
        product_taxes = ProductTax.objects.filter(tenant=request.tenant)
        
        edit_data = None
        if invoice_id:
            try:
                invoice = PurchaseInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                items = []
                for item in invoice.items.all():
                    items.append({
                        'product_id': item.product.id,
                        'name': item.product.product_name,
                        'batch_number': item.batch_number,
                        'expiry_date': item.expiry_date.strftime('%Y-%m'),
                        'quantity': item.quantity,
                        'free_quantity': item.free_quantity,
                        'total_units': (item.quantity + item.free_quantity) * item.product.conversion_factor,
                        'purchase_price': float(item.purchase_price),
                        'tax_percentage': float(item.tax_percentage),
                        'tax_amount': float((item.quantity * item.purchase_price * item.tax_percentage) / 100),
                        'mrp': float(item.mrp),
                        'sale_price': float(item.sale_price),
                        'total': float(item.total_amount)
                    })
                edit_data = {
                    'id': invoice.id,
                    'supplier_id': invoice.supplier.id if invoice.supplier else '',
                    'invoice_number': invoice.invoice_number,
                    'purchase_date': invoice.purchase_date.strftime('%Y-%m-%d') if invoice.purchase_date else '',
                    'items': items,
                    'discount_amount': float(invoice.discount_amount)
                }
            except PurchaseInvoice.DoesNotExist:
                return redirect('purchase_list')
        edit_data = json.dumps(edit_data) if edit_data else None
        
        return render(request, self.template_name, {
            'suppliers': suppliers,
            'products': products,
            'product_taxes': product_taxes,
            'edit_data': edit_data
        })

    def post(self, request, invoice_id=None):
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                # If editing, revert old stock first
                if invoice_id:
                    invoice = PurchaseInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                    for item in invoice.items.all():
                        
                        batch = StockBatch.objects.filter(
                            tenant=request.tenant, product=item.product, batch_number=item.batch_number
                        ).first()
                        if batch:
                            total_units = (item.quantity + item.free_quantity) * item.product.conversion_factor
                            batch.current_quantity -= total_units
                            if batch.current_quantity < 0: batch.current_quantity = 0
                            batch.save()
                    invoice.items.all().delete()
                else:
                    invoice = PurchaseInvoice(tenant=request.tenant, user=request.user)

                supplier = Supplier.objects.get(id=data['supplier_id'], tenant=request.tenant)
                invoice.supplier = supplier
                invoice.invoice_number = data['invoice_number']
                invoice.purchase_date = data['purchase_date']
                invoice.sub_total = data['sub_total']
                invoice.tax_amount = data['tax_amount']
                invoice.discount_percentage = data.get('discount_percentage', 0)
                invoice.discount_amount = data.get('discount_amount', 0)
                invoice.payment_mode = data.get('payment_mode', 'Cash')
                invoice.total_amount = data['total_amount']
                invoice.save()
                
                for item in data['items']:
                    product = Products.objects.get(id=item['product_id'], tenant=request.tenant)
                    # Note: PurchaseItem.save() handles stock addition
                    PurchaseItem.objects.create(
                        tenant=request.tenant,
                        purchase_invoice=invoice,
                        product=product,
                        batch_number=item['batch_number'],
                        expiry_date=item['expiry_date'] if '-' in item['expiry_date'] and len(item['expiry_date']) > 7 else item['expiry_date'] + "-01",
                        quantity=item['quantity'],
                        free_quantity=item.get('free_quantity', 0),
                        purchase_price=item['purchase_price'],
                        mrp=item['mrp'],
                        sale_price=item['sale_price'],
                        tax_percentage=item.get('tax_percentage', 0),
                        total_amount=item['total']
                    )
                
                return JsonResponse({'success': True, 'invoice_id': invoice.id})
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return JsonResponse({'success': False, 'error': str(e)})

class SupplierAutocomplete(View):
    def get(self, request):
        query = request.GET.get('q', '')
        suppliers = Supplier.objects.filter(tenant=request.tenant, name__icontains=query)[:10]
        data = [{'id': s.id, 'name': s.name} for s in suppliers]
        return JsonResponse(data, safe=False)

class PurchaseListView(View):
    template_name = 'purchase/list.html'

    def get(self, request):
        invoices = PurchaseInvoice.objects.filter(tenant=request.tenant).select_related('supplier').order_by('-created_at')
        return render(request, self.template_name, {'invoices': invoices})

    def delete(self, request, invoice_id):
        try:
            with transaction.atomic():
                invoice = PurchaseInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                # When deleting an invoice, we must decrease stock
                for item in invoice.items.all():
                    from easypharma.models.stock import StockBatch
                    batch = StockBatch.objects.get(
                        tenant=request.tenant, 
                        product=item.product, 
                        batch_number=item.batch_number
                    )
                    total_units = (item.quantity + item.free_quantity) * item.product.conversion_factor
                    batch.current_quantity -= total_units
                    if batch.current_quantity < 0: batch.current_quantity = 0
                    batch.save()
                
                invoice.delete()
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})
