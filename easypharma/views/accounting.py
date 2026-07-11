from django.views import View
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db import transaction
from django.utils.timezone import now
import json

from easypharma.models.purchase_invoice import Supplier, PurchaseInvoice
from easypharma.models.sales import Customer
from easypharma.models.accounting import SupplierLedger, SupplierPayment, ExpiryReturn, ExpiryReturnItem, CustomerLedger, CustomerPayment
from easypharma.models.stock import StockBatch

class SupplierLedgerView(View):
    template_name = 'accounting/ledger.html'

    def get(self, request):
        suppliers = Supplier.objects.filter(tenant=request.tenant).order_by('name')
        customers = Customer.objects.filter(tenant=request.tenant).order_by('name')
        
        account_id = request.GET.get('account_id')
        start_date = request.GET.get('start_date')
        end_date = request.GET.get('end_date')
        
        # Fallback to direct query parameters
        if not account_id:
            raw_supplier_id = request.GET.get('supplier_id')
            raw_customer_id = request.GET.get('customer_id')
            if raw_customer_id:
                account_id = f"customer_{raw_customer_id}"
            elif raw_supplier_id:
                account_id = f"supplier_{raw_supplier_id}"

        ledger_entries = []
        running_balance = 0
        selected_account = None
        account_type = None

        if account_id:
            account_id_lower = str(account_id).lower().strip()
            
            if account_id_lower.startswith('customer_') or account_id_lower.startswith('customer:') or account_id_lower.startswith('customer-'):
                account_type = 'customer'
                customer_id = account_id_lower.replace('customer_', '').replace('customer:', '').replace('customer-', '')
                selected_account = get_object_or_404(Customer, id=customer_id, tenant=request.tenant)
                
                # Opening balance for customer (debit - credit)
                opening_balance = 0
                if start_date:
                    prior_entries = CustomerLedger.objects.filter(
                        tenant=request.tenant,
                        customer=selected_account,
                        date__lt=start_date
                    )
                    for entry in prior_entries:
                        opening_balance += entry.debit - entry.credit
                
                running_balance = opening_balance

                # Fetch entries within range
                entries = CustomerLedger.objects.filter(
                    tenant=request.tenant,
                    customer=selected_account
                )
                if start_date:
                    entries = entries.filter(date__gte=start_date)
                if end_date:
                    entries = entries.filter(date__lte=end_date)
                entries = entries.order_by('date', 'id')

                if start_date and opening_balance != 0:
                    ledger_entries.append({
                        'date': start_date,
                        'transaction_type': 'Opening Balance',
                        'reference_number': '-',
                        'debit': 0,
                        'credit': 0,
                        'balance': opening_balance,
                        'remarks': 'Brought Forward'
                    })

                for entry in entries:
                    running_balance += entry.debit - entry.credit
                    ledger_entries.append({
                        'date': entry.date,
                        'transaction_type': entry.transaction_type,
                        'reference_number': entry.reference_number,
                        'debit': entry.debit,
                        'credit': entry.credit,
                        'balance': running_balance,
                        'remarks': entry.remarks,
                    })

            elif account_id_lower.startswith('supplier_') or account_id_lower.startswith('supplier:') or account_id_lower.startswith('supplier-'):
                account_type = 'supplier'
                supplier_id = account_id_lower.replace('supplier_', '').replace('supplier:', '').replace('supplier-', '')
                selected_account = get_object_or_404(Supplier, id=supplier_id, tenant=request.tenant)
                
                # Opening balance for supplier (credit - debit)
                opening_balance = 0
                if start_date:
                    prior_entries = SupplierLedger.objects.filter(
                        tenant=request.tenant,
                        supplier=selected_account,
                        date__lt=start_date
                    )
                    for entry in prior_entries:
                        opening_balance += entry.credit - entry.debit
                
                running_balance = opening_balance

                # Fetch entries within range
                entries = SupplierLedger.objects.filter(
                    tenant=request.tenant,
                    supplier=selected_account
                )
                if start_date:
                    entries = entries.filter(date__gte=start_date)
                if end_date:
                    entries = entries.filter(date__lte=end_date)
                entries = entries.order_by('date', 'id')

                if start_date and opening_balance != 0:
                    ledger_entries.append({
                        'date': start_date,
                        'transaction_type': 'Opening Balance',
                        'reference_number': '-',
                        'debit': 0,
                        'credit': 0,
                        'balance': opening_balance,
                        'remarks': 'Brought Forward'
                    })

                for entry in entries:
                    running_balance += entry.credit - entry.debit
                    ledger_entries.append({
                        'date': entry.date,
                        'transaction_type': entry.transaction_type,
                        'reference_number': entry.reference_number,
                        'debit': entry.debit,
                        'credit': entry.credit,
                        'balance': running_balance,
                        'remarks': entry.remarks,
                        'is_adjusted': getattr(entry, 'is_adjusted', False)
                    })

        return render(request, self.template_name, {
            'account_id': account_id,
            'account_type': account_type,
            'suppliers': suppliers,
            'customers': customers,
            'selected_account': selected_account,
            'ledger_entries': ledger_entries,
            'closing_balance': running_balance,
            'start_date': start_date,
            'end_date': end_date,
            'total_debit': sum(float(e['debit']) for e in ledger_entries if e['transaction_type'] != 'Opening Balance'),
            'total_credit': sum(float(e['credit']) for e in ledger_entries if e['transaction_type'] != 'Opening Balance'),
        })

    def post(self, request):
        account_id = request.POST.get('account_id')
        entry_date = request.POST.get('date')
        entry_type = request.POST.get('entry_type')
        amount = request.POST.get('amount')
        reference_number = request.POST.get('reference_number')
        remarks = request.POST.get('remarks')

        if not account_id or not entry_date or not amount or not entry_type:
            messages.error(request, "Missing required fields for JV entry.")
            return redirect('supplier_ledger')

        try:
            debit_val = 0.00
            credit_val = 0.00
            if entry_type == 'Debit':
                debit_val = float(amount)
            else:
                credit_val = float(amount)

            account_id_lower = str(account_id).lower().strip()

            if account_id_lower.startswith('customer_') or account_id_lower.startswith('customer:') or account_id_lower.startswith('customer-'):
                customer_id = account_id_lower.replace('customer_', '').replace('customer:', '').replace('customer-', '')
                customer = get_object_or_404(Customer, id=customer_id, tenant=request.tenant)
                CustomerLedger.objects.create(
                    tenant=request.tenant,
                    customer=customer,
                    date=entry_date,
                    transaction_type='JV',
                    reference_number=reference_number or '',
                    debit=debit_val,
                    credit=credit_val,
                    remarks=remarks or ''
                )
                messages.success(request, f"Journal Voucher (JV) entry of Rs. {amount} added successfully for customer {customer.name}!")
            elif account_id_lower.startswith('supplier_') or account_id_lower.startswith('supplier:') or account_id_lower.startswith('supplier-'):
                supplier_id = account_id_lower.replace('supplier_', '').replace('supplier:', '').replace('supplier-', '')
                supplier = get_object_or_404(Supplier, id=supplier_id, tenant=request.tenant)
                SupplierLedger.objects.create(
                    tenant=request.tenant,
                    supplier=supplier,
                    date=entry_date,
                    transaction_type='JV',
                    reference_number=reference_number or '',
                    debit=debit_val,
                    credit=credit_val,
                    remarks=remarks or ''
                )
                messages.success(request, f"Journal Voucher (JV) entry of Rs. {amount} added successfully for supplier {supplier.name}!")
        except Exception as e:
            messages.error(request, f"Failed to save JV entry: {str(e)}")
            
        return redirect(f'/accounting/supplier-ledger/?account_id={account_id}')

class SupplierPaymentView(View):
    template_name = 'accounting/supplier_payment.html'

    def get(self, request):
        suppliers = Supplier.objects.filter(tenant=request.tenant)
        payments = SupplierPayment.objects.filter(tenant=request.tenant).order_by('-payment_date')
        return render(request, self.template_name, {
            'suppliers': suppliers,
            'payments': payments,
            'today': now().date()
        })

    def post(self, request):
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                supplier = get_object_or_404(Supplier, id=data['supplier_id'], tenant=request.tenant)
                payment_id = data.get('payment_id')
                
                payment = None
                if payment_id:
                    payment = get_object_or_404(SupplierPayment, id=payment_id, tenant=request.tenant)
                    # Revert previous adjustments
                    if payment.payment_details and 'adjusted_invoices' in payment.payment_details:
                        for adj in payment.payment_details['adjusted_invoices']:
                            try:
                                inv = PurchaseInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                                inv.paid_amount = float(inv.paid_amount) - float(adj['amount'])
                                inv.save()
                            except PurchaseInvoice.DoesNotExist:
                                pass
                    # Delete old ledger
                    ref = payment.reference_number or f"PAY-{payment.id}"
                    SupplierLedger.objects.filter(
                        tenant=request.tenant, supplier=supplier, transaction_type='Payment', reference_number=ref
                    ).delete()
                
                adjusted_invoices = data.get('adjusted_invoices', [])
                payment_details = data.get('payment_details', {})
                payment_details['adjusted_invoices'] = adjusted_invoices

                if payment:
                    payment.payment_date = data['payment_date']
                    payment.amount = data['amount']
                    payment.payment_mode = data['payment_mode']
                    payment.reference_number = data.get('reference_number', '')
                    payment.payment_details = payment_details
                    payment.remarks = data.get('remarks', '')
                    payment.save()
                else:
                    payment = SupplierPayment.objects.create(
                        tenant=request.tenant,
                        supplier=supplier,
                        payment_date=data['payment_date'],
                        amount=data['amount'],
                        payment_mode=data['payment_mode'],
                        reference_number=data.get('reference_number', ''),
                        payment_details=payment_details,
                        remarks=data.get('remarks', '')
                    )

                # Process adjustments
                for adj in adjusted_invoices:
                    inv = PurchaseInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                    adj_amt = float(adj['amount'])
                    inv.paid_amount = float(inv.paid_amount) + adj_amt
                    inv.save()

                SupplierLedger.objects.create(
                    tenant=request.tenant,
                    supplier=supplier,
                    date=data['payment_date'],
                    transaction_type='Payment',
                    reference_number=payment.reference_number or f"PAY-{payment.id}",
                    debit=data['amount'],
                    credit=0,
                    is_adjusted=len(adjusted_invoices) > 0,
                    remarks=f"Payment via {data['payment_mode']}"
                )

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

class SupplierCreditBillsView(View):
    def get(self, request):
        supplier_id = request.GET.get('supplier_id')
        if not supplier_id:
            return JsonResponse([], safe=False)
            
        # Get all invoices for this supplier where paid_amount < total_amount
        # Django ORM can do F expressions
        from django.db.models import F
        invoices = PurchaseInvoice.objects.filter(
            tenant=request.tenant,
            supplier_id=supplier_id,
            total_amount__gt=F('paid_amount')
        ).order_by('purchase_date')
        
        data = []
        for inv in invoices:
            data.append({
                'id': inv.id,
                'invoice_number': inv.invoice_number,
                'purchase_date': inv.purchase_date.strftime('%Y-%m-%d') if inv.purchase_date else '',
                'total_amount': float(inv.total_amount),
                'paid_amount': float(inv.paid_amount),
                'balance': float(inv.total_amount - inv.paid_amount)
            })
            
        return JsonResponse(data, safe=False)

class SupplierUnadjustedReturnsView(View):
    def get(self, request):
        supplier_id = request.GET.get('supplier_id')
        if not supplier_id:
            return JsonResponse([], safe=False)
            
        returns = ExpiryReturn.objects.filter(
            tenant=request.tenant,
            supplier_id=supplier_id
        ).order_by('return_date')
        
        data = []
        for ret in returns:
            allocated = 0.0
            if ret.return_details and 'adjusted_invoices' in ret.return_details:
                allocated = sum(float(adj['amount']) for adj in ret.return_details['adjusted_invoices'])
            
            balance = float(ret.total_amount) - allocated
            if balance > 0:
                data.append({
                    'id': ret.id,
                    'return_date': ret.return_date.strftime('%Y-%m-%d'),
                    'total_amount': float(ret.total_amount),
                    'allocated': allocated,
                    'balance': balance,
                    'reference': f"RET-{ret.id}"
                })
                
        return JsonResponse(data, safe=False)

class ExpiryReturnView(View):
    template_name = 'accounting/expiry_return.html'

    def get(self, request):
        suppliers = Supplier.objects.filter(tenant=request.tenant)
        returns = ExpiryReturn.objects.filter(tenant=request.tenant).order_by('-return_date')
        return render(request, self.template_name, {
            'suppliers': suppliers,
            'returns': returns,
            'today': now().date()
        })

    def post(self, request):
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                supplier = get_object_or_404(Supplier, id=data['supplier_id'], tenant=request.tenant)
                return_id = data.get('return_id')

                expiry_return = None
                if return_id:
                    expiry_return = get_object_or_404(ExpiryReturn, id=return_id, tenant=request.tenant)
                    # Revert previous adjustments
                    if expiry_return.return_details and 'adjusted_invoices' in expiry_return.return_details:
                        for adj in expiry_return.return_details['adjusted_invoices']:
                            try:
                                inv = PurchaseInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                                inv.paid_amount = float(inv.paid_amount) - float(adj['amount'])
                                inv.save()
                            except PurchaseInvoice.DoesNotExist:
                                pass
                    # Revert previous stock quantities
                    for item in expiry_return.items.all():
                        try:
                            batch = StockBatch.objects.get(
                                tenant=request.tenant, product=item.product, batch_number=item.batch_number
                            )
                            batch.current_quantity += int(item.quantity) * batch.product.conversion_factor
                            batch.save()
                        except StockBatch.DoesNotExist:
                            pass
                    # Delete old items and ledger
                    expiry_return.items.all().delete()
                    ref = f"RET-{expiry_return.id}"
                    SupplierLedger.objects.filter(
                        tenant=request.tenant, supplier=supplier, transaction_type='Return', reference_number=ref
                    ).delete()
                
                adjusted_invoices = data.get('adjusted_invoices', [])
                return_details = {'adjusted_invoices': adjusted_invoices}

                if expiry_return:
                    expiry_return.return_date = data['return_date']
                    expiry_return.total_amount = data['total_amount']
                    expiry_return.return_details = return_details
                    expiry_return.remarks = data.get('remarks', '')
                    expiry_return.save()
                else:
                    expiry_return = ExpiryReturn.objects.create(
                        tenant=request.tenant,
                        supplier=supplier,
                        return_date=data['return_date'],
                        total_amount=data['total_amount'],
                        return_details=return_details,
                        remarks=data.get('remarks', '')
                    )
                
                for item in data['items']:
                    batch = StockBatch.objects.get(id=item['batch_id'], tenant=request.tenant)
                    
                    # Decrease stock
                    batch.current_quantity -= int(item['quantity']) * batch.product.conversion_factor
                    if batch.current_quantity < 0:
                        batch.current_quantity = 0
                    batch.save()
                    
                    ExpiryReturnItem.objects.create(
                        tenant=request.tenant,
                        expiry_return=expiry_return,
                        product=batch.product,
                        batch_number=batch.batch_number,
                        quantity=item['quantity'],
                        rate=item['rate'],
                        amount=item['amount']
                    )

                # Process adjustments
                for adj in adjusted_invoices:
                    inv = PurchaseInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                    adj_amt = float(adj['amount'])
                    inv.paid_amount = float(inv.paid_amount) + adj_amt
                    inv.save()

                SupplierLedger.objects.create(
                    tenant=request.tenant,
                    supplier=supplier,
                    date=data['return_date'],
                    transaction_type='Return',
                    reference_number=f"RET-{expiry_return.id}",
                    debit=data['total_amount'],
                    credit=0,
                    is_adjusted=len(adjusted_invoices) > 0,
                    remarks="Expiry Return"
                )

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

class StockBatchAutocomplete(View):
    def get(self, request):
        query = request.GET.get('q', '')
        supplier_id = request.GET.get('supplier_id')
        
        batches = StockBatch.objects.filter(tenant=request.tenant, current_quantity__gt=0)
        if query:
            batches = batches.filter(product__product_name__icontains=query)
            
        data = []
        for b in batches[:15]:
            data.append({
                'id': b.id,
                'product_name': b.product.product_name,
                'batch_number': b.batch_number,
                'expiry_date': b.expiry_date.strftime('%Y-%m-%d') if b.expiry_date else '',
                'purchase_price': float(b.purchase_price),
                'available_qty': b.current_quantity // b.product.conversion_factor
            })
        return JsonResponse(data, safe=False)

class DeleteSupplierPaymentView(View):
    def post(self, request, pk):
        try:
            with transaction.atomic():
                payment = get_object_or_404(SupplierPayment, id=pk, tenant=request.tenant)
                
                # Revert adjustments if they exist
                if payment.payment_details and 'adjusted_invoices' in payment.payment_details:
                    for adj in payment.payment_details['adjusted_invoices']:
                        try:
                            inv = PurchaseInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                            inv.paid_amount = float(inv.paid_amount) - float(adj['amount'])
                            inv.save()
                        except PurchaseInvoice.DoesNotExist:
                            pass
                
                # Find and delete the ledger entry
                ref = payment.reference_number or f"PAY-{payment.id}"
                SupplierLedger.objects.filter(
                    tenant=request.tenant,
                    supplier=payment.supplier,
                    transaction_type='Payment',
                    reference_number=ref
                ).delete()
                
                payment.delete()
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

class DeleteExpiryReturnView(View):
    def post(self, request, pk):
        try:
            with transaction.atomic():
                expiry_return = get_object_or_404(ExpiryReturn, id=pk, tenant=request.tenant)
                
                # Revert adjustments if they exist
                if expiry_return.return_details and 'adjusted_invoices' in expiry_return.return_details:
                    for adj in expiry_return.return_details['adjusted_invoices']:
                        try:
                            inv = PurchaseInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                            inv.paid_amount = float(inv.paid_amount) - float(adj['amount'])
                            inv.save()
                        except PurchaseInvoice.DoesNotExist:
                            pass

                # Revert stock quantities
                for item in expiry_return.items.all():
                    try:
                        batch = StockBatch.objects.get(
                            tenant=request.tenant, 
                            product=item.product, 
                            batch_number=item.batch_number
                        )
                        batch.current_quantity += int(item.quantity) * batch.product.conversion_factor
                        batch.save()
                    except StockBatch.DoesNotExist:
                        pass
                
                # Find and delete the ledger entry
                ref = f"RET-{expiry_return.id}"
                SupplierLedger.objects.filter(
                    tenant=request.tenant,
                    supplier=expiry_return.supplier,
                    transaction_type='Return',
                    reference_number=ref
                ).delete()
                
                expiry_return.delete()
                return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class CustomerPaymentView(View):
    template_name = 'accounting/customer_payment.html'

    def get(self, request):
        customers = Customer.objects.filter(tenant=request.tenant).order_by('name')
        payments = CustomerPayment.objects.filter(tenant=request.tenant).order_by('-payment_date')
        
        # Calculate current receivable balance for each customer
        for c in customers:
            ledger = CustomerLedger.objects.filter(tenant=request.tenant, customer=c)
            total_debit = sum(item.debit for item in ledger)
            total_credit = sum(item.credit for item in ledger)
            c.current_balance = float(total_debit - total_credit)

        return render(request, self.template_name, {
            'customers': customers,
            'payments': payments,
        })

    def post(self, request):
        try:
            data = json.loads(request.body)
            with transaction.atomic():
                customer = get_object_or_404(Customer, id=data['customer_id'], tenant=request.tenant)
                payment_id = data.get('payment_id')
                
                payment = None
                if payment_id:
                    payment = get_object_or_404(CustomerPayment, id=payment_id, tenant=request.tenant)
                    # Revert previous adjustments
                    if payment.payment_details and 'adjusted_invoices' in payment.payment_details:
                        for adj in payment.payment_details['adjusted_invoices']:
                            try:
                                inv = SaleInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                                inv.paid_amount = float(inv.paid_amount) - float(adj['amount'])
                                inv.save()
                            except SaleInvoice.DoesNotExist:
                                pass
                    # Delete old ledger
                    ref = payment.reference_number or f"PAY-{payment.id}"
                    CustomerLedger.objects.filter(
                        tenant=request.tenant, customer=customer, transaction_type='Payment', reference_number=ref
                    ).delete()
                
                adjusted_invoices = data.get('adjusted_invoices', [])
                payment_details = data.get('payment_details', {})
                payment_details['adjusted_invoices'] = adjusted_invoices

                if payment:
                    payment.payment_date = data['payment_date']
                    payment.amount = data['amount']
                    payment.payment_mode = data['payment_mode']
                    payment.reference_number = data.get('reference_number', '')
                    payment.payment_details = payment_details
                    payment.remarks = data.get('remarks', '')
                    payment.save()
                else:
                    payment = CustomerPayment.objects.create(
                        tenant=request.tenant,
                        customer=customer,
                        payment_date=data['payment_date'],
                        amount=data['amount'],
                        payment_mode=data['payment_mode'],
                        reference_number=data.get('reference_number', ''),
                        payment_details=payment_details,
                        remarks=data.get('remarks', '')
                    )

                # Process adjustments
                from easypharma.models.sales import SaleInvoice
                for adj in adjusted_invoices:
                    inv = SaleInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                    adj_amt = float(adj['amount'])
                    inv.paid_amount = float(inv.paid_amount) + adj_amt
                    inv.save()

                CustomerLedger.objects.create(
                    tenant=request.tenant,
                    customer=customer,
                    date=data['payment_date'],
                    transaction_type='Payment',
                    reference_number=payment.reference_number or f"PAY-{payment.id}",
                    debit=0,
                    credit=data['amount'],
                    remarks=data.get('remarks', f"Payment received via {data['payment_mode']}")
                )

            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class DeleteCustomerPaymentView(View):
    def post(self, request, pk):
        payment = get_object_or_404(CustomerPayment, id=pk, tenant=request.tenant)
        try:
            with transaction.atomic():
                from easypharma.models.sales import SaleInvoice
                # Revert adjustments
                if payment.payment_details and 'adjusted_invoices' in payment.payment_details:
                    for adj in payment.payment_details['adjusted_invoices']:
                        try:
                            inv = SaleInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                            inv.paid_amount = float(inv.paid_amount) - float(adj['amount'])
                            inv.save()
                        except SaleInvoice.DoesNotExist:
                            pass
                
                # Delete corresponding CustomerLedger entries
                ref_num = payment.reference_number or f"PAY-{payment.id}"
                CustomerLedger.objects.filter(
                    tenant=request.tenant,
                    customer=payment.customer,
                    transaction_type='Payment',
                    reference_number=ref_num
                ).delete()

                # Delete the payment itself
                payment.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


class CustomerCreditBillsView(View):
    def get(self, request):
        customer_id = request.GET.get('customer_id')
        if not customer_id:
            return JsonResponse([], safe=False)
            
        # Get all invoices for this customer where paid_amount < total_amount and payment_mode is Credit
        from django.db.models import F
        from easypharma.models.sales import SaleInvoice
        invoices = SaleInvoice.objects.filter(
            tenant=request.tenant,
            customer_id=customer_id,
            payment_mode='Credit',
            total_amount__gt=F('paid_amount')
        ).order_by('created_at')
        
        data = []
        for inv in invoices:
            data.append({
                'id': inv.id,
                'invoice_number': inv.invoice_number,
                'created_at': inv.created_at.strftime('%Y-%m-%d') if inv.created_at else '',
                'total_amount': float(inv.total_amount),
                'paid_amount': float(inv.paid_amount),
                'balance': float(inv.total_amount - inv.paid_amount)
            })
            
        return JsonResponse(data, safe=False)
