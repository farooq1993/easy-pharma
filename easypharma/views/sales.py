from django.views import View
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Q
from easypharma.models.Items import Products
from easypharma.models.sales import (SaleInvoice, SaleItem,
                                    Customer, SalesReturn, SalesReturnItem,PrescriptionReminder)
import json
from datetime import datetime
from urllib.parse import quote_plus

from easypharma.models.Items import Products, ProductTax
from easypharma.models.doctor import DoctorModel

class POSView(View):
    template_name = 'sales/pos.html'

    def get(self, request, invoice_id=None):
        products = Products.objects.filter(tenant=request.tenant)
        customers = Customer.objects.filter(tenant=request.tenant)
        product_taxes = ProductTax.objects.filter(tenant=request.tenant)
        default_doctor = DoctorModel.objects.filter(tenant=request.tenant, is_default=True).first()

        edit_invoice = None
        edit_data = None
        if invoice_id:
            try:
                edit_invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                items = []
                for item in edit_invoice.items.all().select_related('product'):
                    # find batch id if available for the same product and batch
                    from easypharma.models.stock import StockBatch
                    batch = StockBatch.objects.filter(
                        tenant=request.tenant,
                        product=item.product,
                        batch_number=item.batch_number
                    ).first()
                    items.append({
                        'product_id': item.product.id,
                        'batch_id': batch.id if batch else None,
                        'product_name': item.product.product_name,
                        'batch_number': item.batch_number,
                        'expiry_date': item.expiry_date.strftime('%Y-%m-%d') if item.expiry_date else '',
                        'quantity': item.quantity,
                        'price': float(item.unit_price),
                        'tax_rate': float(item.tax_percentage),
                        'total': float(item.total_amount),
                        'discount_percentage': float(item.discount_percentage or 0)
                    })

                gross_amount = float(edit_invoice.sub_total or 0) + float(edit_invoice.tax_amount or 0)
                discount_amount = float(edit_invoice.discount_amount or 0)
                discount_percentage = gross_amount > 0 and (discount_amount / gross_amount) * 100 or 0

                edit_data = {
                    'invoice_id': edit_invoice.id,
                    'invoice_number': edit_invoice.invoice_number,
                    'patient_name': edit_invoice.patient_name,
                    'patient_phone': edit_invoice.patient_phone,
                    'doctor_name': edit_invoice.doctor_name,
                    'payment_mode': edit_invoice.payment_mode,
                    'discount_amount': discount_amount,
                    'discount_percentage': discount_percentage,
                    'items': items
                }
            except SaleInvoice.DoesNotExist:
                edit_data = None
        count = SaleInvoice.objects.filter(tenant=request.tenant).count()
        next_invoice_number = f"INV-{request.tenant.id}-{count + 1}"
        return render(request, self.template_name, {
            'products': products,
            'customers': customers,
            'product_taxes': product_taxes,
            'default_doctor': default_doctor,
            'edit_data': edit_data,
            'next_invoice_number': next_invoice_number,
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
                
                invoice_id = data.get('invoice_id')
                if invoice_id:
                    invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                    # revert stock from previous items before editing
                    for old_item in invoice.items.all():
                        from easypharma.models.stock import StockBatch
                        batch = StockBatch.objects.filter(
                            tenant=request.tenant,
                            product=old_item.product,
                            batch_number=old_item.batch_number
                        ).first()
                        if batch:
                            batch.current_quantity += old_item.quantity
                            batch.save()
                    invoice.items.all().delete()
                else:
                    invoice = SaleInvoice(
                        tenant=request.tenant,
                        user=request.user,
                        invoice_number=invoice_no
                    )
                

                invoice.patient_name = data.get('patient_name')
                invoice.patient_address = data.get('patient_address')
                invoice.patient_phone = data.get('patient_phone')
                invoice.doctor_name = data.get('doctor_name')
                invoice.sub_total = data['sub_total']
                invoice.tax_amount = data['tax_amount']
                invoice.discount_amount = data['discount_amount']
                invoice.total_amount = data['total_amount']
                invoice.payment_mode = data['payment_mode']
                invoice.sale_type = data.get('sale_type', 'Prescription')
                if data.get('invoice_number'):
                    invoice.invoice_number = data['invoice_number']
                invoice.save()
                
                # Create Sale Items & Deduct Stock
                for item in data.get('items', []):
                    product = Products.objects.get(id=item['product_id'], tenant=request.tenant)
                    
                    # Deduct from SPECIFIC batch selected in POS
                    batch_id = item.get('batch_id')
                    if batch_id:
                        batch = StockBatch.objects.get(id=batch_id, tenant=request.tenant)
                    else:
                        # Fallback to FIFO if no batch_id (should not happen with new UI)
                        batch = StockBatch.objects.filter(
                            tenant=request.tenant, 
                            product=product,
                            current_quantity__gt=0
                        ).order_by('expiry_date').first()
                    
                    if not batch:
                        raise Exception(f"No stock available for {product.product_name}")
                    
                    # Calculate tax from product master
                    tax_rate = product.product_tax.tax_rate if product.product_tax else 0
                    quantity = item['quantity']
                    
                    # Calculate base price (since MRP is tax-inclusive)
                    unit_price = item['price']
                    base_price = unit_price / (1 + tax_rate / 100) if tax_rate > 0 else unit_price
                    tax_per_unit = unit_price - base_price
                    tax_amount = tax_per_unit * quantity
                    
                    SaleItem.objects.create(
                        tenant=request.tenant,
                        sale_invoice=invoice,
                        product=product,
                        batch_number=batch.batch_number,
                        expiry_date=batch.expiry_date,
                        quantity=quantity,
                        unit_price=unit_price,
                        tax_percentage=tax_rate,
                        tax_amount=tax_amount,
                        total_amount=item['total']
                    )
                    
                    # Update stock batch
                    batch.current_quantity -= quantity
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
        from easypharma.models.print_setup import PrintSetup
        invoice = get_object_or_404(SaleInvoice, id=invoice_id)
        if not invoice.tenant and request.tenant:
            invoice.tenant = request.tenant
        # Load print settings (use tenant from invoice or request)
        tenant = invoice.tenant or request.tenant
        ps, _ = PrintSetup.objects.get_or_create(tenant=tenant)
        return render(request, self.template_name, {'invoice': invoice, 'ps': ps})

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
        
        products = Products.objects.filter(
            tenant=request.tenant,
            product_name__icontains=query
        ).select_related('product_tax', 'product_content', 'compny_name').prefetch_related('batches')[:10]
        data = []
        for p in products:
            batches = p.batches.filter(current_quantity__gt=0).order_by('expiry_date')
            
            if not batches.exists():
                # Still return the product but flag as out of stock so UI can show substitute button
                data.append({
                    'id': p.id,
                    'name': p.product_name,
                    'packing': p.product_packing,
                    'content': p.product_content.content_name if p.product_content else None,
                    'company': p.compny_name.company_name if p.compny_name else None,
                    'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                    'conversion_factor': p.conversion_factor,
                    'out_of_stock': True,
                    'batches': []
                })
                continue
                
            batch_list = []
            for batch in batches:
                unit_price = float(batch.sale_price)
                if p.conversion_factor > 1:
                    unit_price = float(batch.mrp) / p.conversion_factor
                elif unit_price == 0 and batch.mrp:
                    unit_price = float(batch.mrp)
                
                batch_list.append({
                    'batch_id': batch.id,
                    'batch_no': batch.batch_number,
                    'expiry': batch.expiry_date.strftime('%m/%y'),
                    'stock': batch.current_quantity,
                    'price': unit_price,
                    'mrp_pack': float(batch.mrp)
                })
            
            data.append({
                'id': p.id,
                'name': p.product_name,
                'packing': p.product_packing,
                'content': p.product_content.content_name if p.product_content else None,
                'schedule': p.product_schedule.schedule_name if p.product_schedule else None,
                'company': p.compny_name.company_name if p.compny_name else None,
                'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                'conversion_factor': p.conversion_factor,
                'out_of_stock': False,
                'batches': batch_list
            })
        return JsonResponse(data, safe=False)


class SubstituteSearchAPI(View):
    """Returns in-stock drugs with the same content/composition as the given product."""
    def get(self, request):
        product_id = request.GET.get('product_id')
        if not product_id:
            return JsonResponse([], safe=False)
        
        from easypharma.models.stock import StockBatch
        try:
            source = Products.objects.select_related('product_content').get(
                id=product_id, tenant=request.tenant
            )
        except Products.DoesNotExist:
            return JsonResponse([], safe=False)
        
        if not source.product_content:
            return JsonResponse([], safe=False)
        
        # Find other products with same content that have stock
        subs = Products.objects.filter(
            tenant=request.tenant,
            product_content=source.product_content,
        ).exclude(id=source.id).select_related(
            'product_tax', 'product_content', 'compny_name'
        ).prefetch_related('batches')[:15]
        
        data = []
        for p in subs:
            batches = p.batches.filter(current_quantity__gt=0).order_by('expiry_date')
            if not batches.exists():
                continue
            batch_list = []
            for batch in batches:
                unit_price = float(batch.sale_price)
                if p.conversion_factor > 1:
                    unit_price = float(batch.mrp) / p.conversion_factor
                elif unit_price == 0 and batch.mrp:
                    unit_price = float(batch.mrp)
                batch_list.append({
                    'batch_id': batch.id,
                    'batch_no': batch.batch_number,
                    'expiry': batch.expiry_date.strftime('%m/%y'),
                    'stock': batch.current_quantity,
                    'price': unit_price,
                })
            data.append({
                'id': p.id,
                'name': p.product_name,
                'packing': p.product_packing,
                'company': p.compny_name.company_name if p.compny_name else '—',
                'content': source.product_content.content_name,
                'tax_rate': p.product_tax.tax_rate if p.product_tax else 0,
                'conversion_factor': p.conversion_factor,
                'batches': batch_list,
            })
        
        return JsonResponse(data, safe=False)


class SalesReturnView(View):
    template_name = 'sales/sales_return.html'

    def get(self, request):
        customers = Customer.objects.filter(tenant=request.tenant).order_by('name')
        customer_id = request.GET.get('customer_id')
        customer_name = request.GET.get('customer_name', '').strip()
        invoice_id = request.GET.get('invoice_id')
        
        context = {
            'customers': customers,
            'selected_customer': None,
            'selected_customer_name': None,
            'invoices': [],
            'selected_invoice': None,
            'sale_items': [],
            'returns': SalesReturn.objects.filter(tenant=request.tenant).order_by('-return_at')[:10]  # Recent returns
        }
        
        if customer_id:
            try:
                customer = Customer.objects.get(id=customer_id, tenant=request.tenant)
                context['selected_customer'] = customer
                context['selected_customer_name'] = customer.name
                context['invoices'] = SaleInvoice.objects.filter(
                    tenant=request.tenant
                ).filter(
                    Q(customer=customer) |
                    Q(patient_name__iexact=customer.name) |
                    Q(patient_phone__icontains=customer.phone)
                ).order_by('-created_at')
            except Customer.DoesNotExist:
                messages.error(request, 'Customer not found.')
        elif customer_name:
            context['selected_customer_name'] = customer_name
            context['invoices'] = SaleInvoice.objects.filter(
                tenant=request.tenant
            ).filter(
                Q(patient_name__iexact=customer_name) |
                Q(patient_name__icontains=customer_name) |
                Q(patient_phone__icontains=customer_name)
            ).order_by('-created_at')
            if not context['invoices']:
                messages.error(request, 'No invoices found for this customer name.')
        
        if invoice_id:
            try:
                invoice = SaleInvoice.objects.get(id=invoice_id, tenant=request.tenant)
                context['selected_invoice'] = invoice
                context['sale_items'] = invoice.items.all().select_related('product')
            except SaleInvoice.DoesNotExist:
                messages.error(request, 'Invoice not found.')
        
        return render(request, self.template_name, context)

    def post(self, request):
        action = request.POST.get('action')
        
        if action == 'select_customer':
            customer_id = request.POST.get('customer_id')
            customer_name = request.POST.get('customer_name', '').strip()
            if customer_id:
                return redirect(f"{request.path}?customer_id={customer_id}")
            if customer_name:
                customer = Customer.objects.filter(
                    tenant=request.tenant
                ).filter(
                    Q(name__iexact=customer_name) |
                    Q(name__icontains=customer_name) |
                    Q(phone__icontains=customer_name)
                ).first()
                if customer:
                    return redirect(f"{request.path}?customer_id={customer.id}")
                return redirect(f"{request.path}?customer_name={quote_plus(customer_name)}")
            messages.error(request, 'Please select a valid customer from the list.')
            return redirect('pos_returns')
        
        elif action == 'select_invoice':
            customer_id = request.POST.get('customer_id')
            customer_name = request.POST.get('customer_name', '').strip()
            invoice_id = request.POST.get('invoice_id')
            if invoice_id:
                if customer_id:
                    return redirect(f"{request.path}?customer_id={customer_id}&invoice_id={invoice_id}")
                if customer_name:
                    return redirect(f"{request.path}?customer_name={quote_plus(customer_name)}&invoice_id={invoice_id}")
                return redirect(f"{request.path}?invoice_id={invoice_id}")
            else:
                messages.error(request, 'Please select an invoice.')
                if customer_id:
                    return redirect(f"{request.path}?customer_id={customer_id}")
                if customer_name:
                    return redirect(f"{request.path}?customer_name={quote_plus(customer_name)}")
                return redirect('pos_returns')
        
        elif action == 'process_return':
            invoice_id = request.POST.get('invoice_id')
            return_items = request.POST.getlist('return_items[]')
            return_quantities = request.POST.getlist('return_quantities[]')
            return_reasons = request.POST.getlist('return_reasons[]')
            
            if not invoice_id:
                messages.error(request, 'Invoice not found.')
                return redirect('pos_returns')
            
            invoice = get_object_or_404(SaleInvoice, id=invoice_id, tenant=request.tenant)
            
            if not return_items:
                messages.error(request, 'Please select items to return.')
                return redirect(request.META.get('HTTP_REFERER', 'pos_returns'))
            
            try:
                with transaction.atomic():
                    # Create sales return record
                    return_record = SalesReturn.objects.create(
                        tenant=request.tenant,
                        sale_invoice=invoice,
                        return_qty=0  # Will be calculated from items
                    )
                    
                    total_returned_qty = 0
                    from easypharma.models.stock import StockBatch
                    
                    for i, item_id in enumerate(return_items):
                        sale_item = SaleItem.objects.get(id=item_id, sale_invoice=invoice)
                        qty_to_return = int(return_quantities[i])
                        reason = return_reasons[i] if i < len(return_reasons) else ''
                        
                        if qty_to_return > 0 and qty_to_return <= sale_item.quantity:
                            # Create return item record
                            SalesReturnItem.objects.create(
                                tenant=request.tenant,
                                sales_return=return_record,
                                sale_item=sale_item,
                                returned_quantity=qty_to_return,
                                return_reason=reason
                            )
                            
                            # Restore stock
                            StockBatch.objects.filter(
                                tenant=request.tenant,
                                product=sale_item.product,
                                batch_number=sale_item.batch_number
                            ).update(current_quantity=F('current_quantity') + qty_to_return)
                            
                            total_returned_qty += qty_to_return
                    
                    # Update total return quantity
                    return_record.return_qty = total_returned_qty
                    return_record.save()
                    
                    messages.success(request, f"Sales return created ({return_record.return_inv_no}). {total_returned_qty} items returned and stock restored.")
                    
            except Exception as e:
                messages.error(request, f"Unable to process return: {e}")
            
            return redirect('pos_returns')
        
        return redirect('pos_returns')


class PatientWiseSales(View):
    template_name = "sales/patient_wise_sales.html"

    def get(self, request):
        return render(request, self.template_name)


class PatientWiseSalesAPI(View):
    def get(self, request):
        patient_name = request.GET.get('patient_name', '').strip()
        if not patient_name:
            return JsonResponse({'error': 'Patient name is required'}, status=400)
        
        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            patient_name__icontains=patient_name
        ).order_by('-created_at')
        
        data = []
        for sale in sales:
            items = []
            for item in sale.items.all().select_related('product'):
                items.append({
                    'product_name': item.product.product_name,
                    'batch_number': item.batch_number,
                    'expiry_date': item.expiry_date.strftime('%Y-%m-%d') if item.expiry_date else '',
                    'quantity': item.quantity,
                    'unit_price': float(item.unit_price),
                    'total': float(item.total_amount)
                })
            data.append({
                'invoice_number': sale.invoice_number,
                'date': sale.created_at.strftime('%Y-%m-%d %H:%M'),
                'doctor_name': sale.doctor_name,
                'payment_mode': sale.payment_mode,
                'total_amount': float(sale.total_amount),
                'items': items
            })
        
        return JsonResponse(data, safe=False)


class PrescriptionReminderView(View):
    template_name = "sales/prescription_reminders.html"

    def get(self, request):
        reminders = PrescriptionReminder.objects.filter(tenant=request.tenant).order_by('reminder_date')
        customers = SaleInvoice.objects.filter(tenant=request.tenant).exclude(patient_name__isnull=True).exclude(
                    patient_name='').values_list('patient_name',flat=True).distinct().order_by('patient_name')

        inv_items = SaleItem.objects.filter(sale_invoice__tenant=request.tenant).select_related('sale_invoice', 'product')
        reminders = PrescriptionReminder.objects.filter(tenant=request.tenant).order_by('reminder_date')

        
        return render(request, self.template_name, {
            'reminders': reminders,
            'customers': customers,
            'inv_items': inv_items,
            'today': timezone.now().date()   # for status badge
        })
    
    def post(self, request):
        patient_name = request.POST.get('customer_id')
        prescription_date = request.POST.get('prescription_date')
        reminder_date = request.POST.get('reminder_date')
        notes = request.POST.get('notes', '').strip()
        
        if not (patient_name and prescription_date and reminder_date):
            messages.error(request, 'Customer, prescription date, and reminder date are required.')
            return redirect('prescription_reminders')
        
        try:
            patient_name = request.POST.get('customer_id')
            reminder = PrescriptionReminder.objects.create(
                tenant=request.tenant,
                patient_name=patient_name,
                prescription_date=prescription_date,
                reminder_date=reminder_date,
                notes=notes
            )
            messages.success(request, f"Reminder set for {patient_name} on {reminder.reminder_date}.")
        except Customer.DoesNotExist:
            messages.error(request, 'Customer not found.')
        except Exception as e:
            messages.error(request, f"Error creating reminder: {e}")
        
        return redirect('prescription_reminders')
    
class PrescriptionReminderDeleteView(View):

    def post(self, request, reminder_id):

        try:
            reminder = PrescriptionReminder.objects.get(
                id=reminder_id,
                tenant=request.tenant
            )

            reminder.delete()

            return JsonResponse({
                'success': True
            })

        except PrescriptionReminder.DoesNotExist:

            return JsonResponse({
                'success': False,
                'error': 'Reminder not found'
            })

# ==================== NEW AJAX VIEW ====================
def get_customer_invoices(request):

    patient_name = request.GET.get('patient_name')

    items = SaleItem.objects.filter(
        sale_invoice__tenant=request.tenant,
        sale_invoice__patient_name=patient_name
    ).select_related(
        'sale_invoice',
        'product'
    )

    data = []

    for item in items:
        data.append({
            'id': item.id,
            'product_name': item.product.product_name,
            'invoice_number': item.sale_invoice.invoice_number,
        })

    return JsonResponse({
        'products': data
    })