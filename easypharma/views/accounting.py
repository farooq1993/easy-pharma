from django.views import View
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.db import transaction
from django.utils.timezone import now
import json
from django.contrib.auth.mixins import LoginRequiredMixin

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
            
        # Get all Credit invoices for this supplier where paid_amount < total_amount
        from django.db.models import F
        invoices = PurchaseInvoice.objects.filter(
            tenant=request.tenant,
            supplier_id=supplier_id,
            payment_mode='Credit',
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

            return JsonResponse({'success': True, 'payment_id': payment.id})
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


class PrintCustomerPaymentReceiptView(LoginRequiredMixin, View):
    def get(self, request, pk):
        from easypharma.models.print_setup import PrintSetup
        payment = get_object_or_404(CustomerPayment, id=pk, tenant=request.tenant)
        ps, _ = PrintSetup.objects.get_or_create(tenant=request.tenant)
        
        # Get adjusted invoices if any
        adjusted_invoices = []
        if payment.payment_details and 'adjusted_invoices' in payment.payment_details:
            from easypharma.models.sales import SaleInvoice
            for adj in payment.payment_details['adjusted_invoices']:
                try:
                    inv = SaleInvoice.objects.get(id=adj['id'], tenant=request.tenant)
                    adjusted_invoices.append({
                        'invoice_number': inv.invoice_number,
                        'date': inv.created_at.strftime('%Y-%m-%d') if inv.created_at else '',
                        'amount': adj['amount']
                    })
                except SaleInvoice.DoesNotExist:
                    pass

        return render(request, 'accounting/print_payment_receipt.html', {
            'payment': payment,
            'ps': ps,
            'adjusted_invoices': adjusted_invoices,
        })


class SupplierOutstandingView(LoginRequiredMixin, View):
    template_name = 'accounting/supplier_outstanding.html'

    def dispatch(self, request, *args, **kwargs):
        from easypharma.permissions import has_module_permission
        if not has_module_permission(request.user, 'accounting'):
            messages.error(request, "Access denied. You do not have permission to access the Accounting module.")
            return redirect('home')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request):
        from django.core.paginator import Paginator

        supplier_id = request.GET.get('supplier_id', 'all').strip()
        search_query = request.GET.get('q', '').strip()
        view_type = request.GET.get('view_type', 'summary').strip().lower()
        status_filter = request.GET.get('status', 'outstanding').strip().lower()
        start_date = request.GET.get('start_date', '').strip()
        end_date = request.GET.get('end_date', '').strip()
        export = request.GET.get('export', '').strip().lower()

        page = request.GET.get('page', 1)
        page_size_str = request.GET.get('page_size', '25').strip()
        try:
            page_size = int(page_size_str)
            if page_size not in [10, 25, 50, 100]:
                page_size = 25
        except (ValueError, TypeError):
            page_size = 25

        from django.db.models import F, Q

        # Fetch only suppliers who have pending outstanding balance
        outstanding_supplier_ids = PurchaseInvoice.objects.filter(
            tenant=request.tenant,
            payment_mode='Credit',
            total_amount__gt=F('paid_amount')
        ).values_list('supplier_id', flat=True).distinct()

        all_pending_suppliers = Supplier.objects.filter(
            tenant=request.tenant,
            id__in=outstanding_supplier_ids
        ).order_by('name')

        suppliers = all_pending_suppliers
        if search_query:
            suppliers = suppliers.filter(
                Q(name__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(gst_number__icontains=search_query)
            )

        selected_supplier = None
        if supplier_id and supplier_id != 'all':
            if str(supplier_id).isdigit():
                try:
                    selected_supplier = Supplier.objects.get(id=int(supplier_id), tenant=request.tenant)
                except (Supplier.DoesNotExist, ValueError):
                    selected_supplier = None
            else:
                selected_supplier = Supplier.objects.filter(
                    tenant=request.tenant,
                    name__iexact=str(supplier_id).strip()
                ).first()
                if not selected_supplier:
                    # partial search
                    suppliers = suppliers.filter(
                        Q(name__icontains=supplier_id) | Q(phone__icontains=supplier_id)
                    )

        if selected_supplier and not suppliers.filter(id=selected_supplier.id).exists():
            suppliers = (suppliers | Supplier.objects.filter(id=selected_supplier.id)).order_by('name')

        today = now().date()

        if view_type == 'details':
            # Detailed bill-wise breakdown
            invoices_qs = PurchaseInvoice.objects.filter(tenant=request.tenant).select_related('supplier')
            if selected_supplier:
                invoices_qs = invoices_qs.filter(supplier=selected_supplier)
            if search_query:
                invoices_qs = invoices_qs.filter(
                    Q(supplier__name__icontains=search_query) |
                    Q(supplier__phone__icontains=search_query) |
                    Q(invoice_number__icontains=search_query) |
                    Q(voucher_number__icontains=search_query)
                )
            if start_date:
                invoices_qs = invoices_qs.filter(purchase_date__gte=start_date)
            if end_date:
                invoices_qs = invoices_qs.filter(purchase_date__lte=end_date)
            
            from django.db.models import F
            if status_filter == 'outstanding':
                # Cash bills are fully paid upon purchase, so outstanding only applies to Credit bills with remaining balance
                invoices_qs = invoices_qs.filter(payment_mode='Credit', total_amount__gt=F('paid_amount'))

            invoices_qs = invoices_qs.order_by('-purchase_date', '-id')

            bills = []
            grand_total_amount = 0.0
            grand_total_paid = 0.0
            grand_total_outstanding = 0.0

            for inv in invoices_qs:
                tot = float(inv.total_amount or 0)
                is_cash = (inv.payment_mode == 'Cash')

                if is_cash:
                    # Cash invoices are 100% paid at purchase
                    paid = tot
                    bal = 0.0
                    status_text = 'Paid'
                    status_badge = 'bg-success'
                else:
                    # Credit invoices
                    paid = float(inv.paid_amount or 0)
                    bal = max(0.0, float(tot - paid))
                    if paid <= 0.001:
                        status_text = 'Unpaid'
                        status_badge = 'bg-danger'
                    elif bal <= 0.001:
                        status_text = 'Paid'
                        status_badge = 'bg-success'
                    else:
                        status_text = 'Partially Paid'
                        status_badge = 'bg-warning text-dark'

                days = (today - inv.purchase_date).days if inv.purchase_date else 0

                bills.append({
                    'id': inv.id,
                    'purchase_date': inv.purchase_date,
                    'invoice_number': inv.invoice_number,
                    'voucher_number': inv.voucher_number or '—',
                    'supplier_id': inv.supplier.id if inv.supplier else None,
                    'supplier_name': inv.supplier.name if inv.supplier else 'Unknown',
                    'supplier_phone': inv.supplier.phone if inv.supplier else '',
                    'payment_mode': inv.payment_mode,
                    'total_amount': tot,
                    'paid_amount': paid,
                    'outstanding': bal,
                    'days': days,
                    'status_text': status_text,
                    'status_badge': status_badge,
                })
                grand_total_amount += tot
                grand_total_paid += paid
                grand_total_outstanding += bal

            # CSV Export
            if export == 'csv':
                import csv
                from django.http import HttpResponse
                response = HttpResponse(content_type='text/csv')
                filename = f"Supplier_Outstanding_Details_{today.strftime('%Y%m%d')}.csv"
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                writer = csv.writer(response)
                writer.writerow(['EasyPharma - Supplier Outstanding Details Report'])
                writer.writerow([f'As on: {today.strftime("%d-%b-%Y")} | Supplier: {selected_supplier.name if selected_supplier else "All Suppliers"} | Status: {status_filter.capitalize()}'])
                writer.writerow([])
                writer.writerow(['#', 'Date', 'Supplier Name', 'Invoice No', 'Voucher No', 'Payment Mode', 'Total Amount (Rs.)', 'Paid Amount (Rs.)', 'Outstanding Balance (Rs.)', 'Ageing (Days)', 'Status'])
                for idx, b in enumerate(bills, 1):
                    writer.writerow([
                        idx,
                        b['purchase_date'].strftime('%Y-%m-%d') if b['purchase_date'] else '',
                        b['supplier_name'],
                        b['invoice_number'],
                        b['voucher_number'],
                        b['payment_mode'],
                        f"{b['total_amount']:.2f}",
                        f"{b['paid_amount']:.2f}",
                        f"{b['outstanding']:.2f}",
                        b['days'],
                        b['status_text']
                    ])
                writer.writerow([])
                writer.writerow(['Total', '', '', '', '', '', f"{grand_total_amount:.2f}", f"{grand_total_paid:.2f}", f"{grand_total_outstanding:.2f}", '', ''])
                return response

            # Pagination for Details
            paginator = Paginator(bills, page_size)
            page_obj = paginator.get_page(page)

            context = {
                'suppliers': suppliers,
                'all_pending_suppliers': all_pending_suppliers,
                'supplier_id': supplier_id,
                'search_query': search_query,
                'selected_supplier': selected_supplier,
                'view_type': 'details',
                'status_filter': status_filter,
                'start_date': start_date,
                'end_date': end_date,
                'bills': page_obj,
                'page_obj': page_obj,
                'paginator': paginator,
                'page_size': page_size,
                'total_bills_count': len(bills),
                'grand_total_amount': grand_total_amount,
                'grand_total_paid': grand_total_paid,
                'grand_total_outstanding': grand_total_outstanding,
                'unique_suppliers_count': len(set(b['supplier_name'] for b in bills if b['outstanding'] > 0.001)),
            }
            return render(request, self.template_name, context)

        else:
            # Summary View - High performance single aggregated query
            from django.db.models import Sum, Count, Q, F, DecimalField, Value
            from django.db.models.functions import Coalesce

            invoices_qs = PurchaseInvoice.objects.filter(tenant=request.tenant)
            if start_date:
                invoices_qs = invoices_qs.filter(purchase_date__gte=start_date)
            if end_date:
                invoices_qs = invoices_qs.filter(purchase_date__lte=end_date)
            if selected_supplier:
                invoices_qs = invoices_qs.filter(supplier=selected_supplier)

            # Aggregate per supplier in ONE single query
            # Cash invoices are 100% paid upon purchase; Credit invoices check remaining balance
            supplier_stats = invoices_qs.values('supplier_id').annotate(
                total_invoices=Count('id'),
                pending_invoices=Count('id', filter=Q(payment_mode='Credit', total_amount__gt=F('paid_amount'))),
                total_amt=Coalesce(Sum('total_amount'), Value(0, output_field=DecimalField())),
                cash_paid=Coalesce(Sum('total_amount', filter=Q(payment_mode='Cash')), Value(0, output_field=DecimalField())),
                credit_paid=Coalesce(Sum('paid_amount', filter=Q(payment_mode='Credit')), Value(0, output_field=DecimalField())),
            )
            stats_map = {item['supplier_id']: item for item in supplier_stats}

            target_suppliers = [selected_supplier] if selected_supplier else list(suppliers)
            summary_list = []
            grand_total_invoices = 0
            grand_total_pending_invoices = 0
            grand_total_amount = 0.0
            grand_total_paid = 0.0
            grand_total_outstanding = 0.0
            suppliers_with_balance_count = 0

            for sup in target_suppliers:
                if not sup:
                    continue
                stat = stats_map.get(sup.id)
                inv_count = stat['total_invoices'] if stat else 0
                pending_inv_count = stat['pending_invoices'] if stat else 0
                tot_amt = float(stat['total_amt']) if stat else 0.0
                cash_amt = float(stat['cash_paid']) if stat else 0.0
                credit_amt = float(stat['credit_paid']) if stat else 0.0
                paid_amt = cash_amt + credit_amt
                bal_amt = max(0.0, tot_amt - paid_amt)

                # Filter by status if requested
                if status_filter == 'outstanding' and bal_amt <= 0.001 and not selected_supplier:
                    continue
                elif status_filter == 'all' and inv_count == 0 and not selected_supplier:
                    continue

                if bal_amt > 0.001:
                    suppliers_with_balance_count += 1

                summary_list.append({
                    'supplier': sup,
                    'total_invoices': inv_count,
                    'pending_invoices': pending_inv_count,
                    'total_amount': tot_amt,
                    'paid_amount': paid_amt,
                    'outstanding': bal_amt,
                })

                grand_total_invoices += inv_count
                grand_total_pending_invoices += pending_inv_count
                grand_total_amount += tot_amt
                grand_total_paid += paid_amt
                grand_total_outstanding += bal_amt

            # CSV Export
            if export == 'csv':
                import csv
                from django.http import HttpResponse
                response = HttpResponse(content_type='text/csv')
                filename = f"Supplier_Outstanding_Summary_{today.strftime('%Y%m%d')}.csv"
                response['Content-Disposition'] = f'attachment; filename="{filename}"'
                writer = csv.writer(response)
                writer.writerow(['EasyPharma - Supplier Outstanding Summary Report'])
                writer.writerow([f'As on: {today.strftime("%d-%b-%Y")} | Supplier: {selected_supplier.name if selected_supplier else "All Suppliers"} | Status: {status_filter.capitalize()}'])
                writer.writerow([])
                writer.writerow(['#', 'Supplier Name', 'Phone', 'GST Number', 'Total Bills', 'Pending Bills', 'Total Purchases (Rs.)', 'Total Paid (Rs.)', 'Net Outstanding (Rs.)'])
                for idx, item in enumerate(summary_list, 1):
                    writer.writerow([
                        idx,
                        item['supplier'].name,
                        item['supplier'].phone or '',
                        item['supplier'].gst_number or '',
                        item['total_invoices'],
                        item['pending_invoices'],
                        f"{item['total_amount']:.2f}",
                        f"{item['paid_amount']:.2f}",
                        f"{item['outstanding']:.2f}"
                    ])
                writer.writerow([])
                writer.writerow(['Total', '', '', '', grand_total_invoices, grand_total_pending_invoices, f"{grand_total_amount:.2f}", f"{grand_total_paid:.2f}", f"{grand_total_outstanding:.2f}"])
                return response

            # Pagination for Summary
            paginator = Paginator(summary_list, page_size)
            page_obj = paginator.get_page(page)

            context = {
                'suppliers': suppliers,
                'all_pending_suppliers': all_pending_suppliers,
                'supplier_id': supplier_id,
                'search_query': search_query,
                'selected_supplier': selected_supplier,
                'view_type': 'summary',
                'status_filter': status_filter,
                'start_date': start_date,
                'end_date': end_date,
                'summary_list': page_obj,
                'page_obj': page_obj,
                'paginator': paginator,
                'page_size': page_size,
                'grand_total_invoices': grand_total_invoices,
                'grand_total_pending_invoices': grand_total_pending_invoices,
                'grand_total_amount': grand_total_amount,
                'grand_total_paid': grand_total_paid,
                'grand_total_outstanding': grand_total_outstanding,
                'suppliers_with_balance_count': suppliers_with_balance_count,
            }
            return render(request, self.template_name, context)
