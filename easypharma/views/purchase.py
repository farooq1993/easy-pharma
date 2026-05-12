from django.views import View
from django.shortcuts import render, redirect
from django.http import JsonResponse
from easypharma.models.Items import Products
from easypharma.models.purchase_invoice import Supplier, PurchaseInvoice, PurchaseItem
from django.db import transaction
import json

class PurchaseEntryView(View):
    template_name = 'purchase/entry.html'

    def get(self, request):
        suppliers = Supplier.objects.filter(tenant=request.tenant)
        products = Products.objects.filter(tenant=request.tenant)
        from easypharma.models.Items import ProductTax
        product_taxes = ProductTax.objects.filter(tenant=request.tenant)
        return render(request, self.template_name, {
            'suppliers': suppliers,
            'products': products,
            'product_taxes': product_taxes
        })

    def post(self, request):
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                supplier = Supplier.objects.get(id=data['supplier_id'], tenant=request.tenant)
                
                invoice = PurchaseInvoice.objects.create(
                    tenant=request.tenant,
                    user=request.user,
                    supplier=supplier,
                    invoice_number=data['invoice_number'],
                    purchase_date=data['purchase_date'],
                    sub_total=data['sub_total'],
                    tax_amount=data['tax_amount'],
                    discount_amount=data['discount_amount'],
                    total_amount=data['total_amount']
                )
                
                for item in data['items']:
                    product = Products.objects.get(id=item['product_id'], tenant=request.tenant)
                    PurchaseItem.objects.create(
                        tenant=request.tenant,
                        purchase_invoice=invoice,
                        product=product,
                        batch_number=item['batch_number'],
                        expiry_date=item['expiry_date'],
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
