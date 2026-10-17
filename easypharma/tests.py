from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory, TestCase
from django.utils import timezone

import json
from easypharma.models.Items import Products
from easypharma.models.general_setup import GeneralSetup
from easypharma.models.sales import SaleInvoice, SaleItem, SalesReturn, SalesReturnItem
from easypharma.models.stock import StockBatch
from easypharma.views.reports import DailySaleReportView
from easypharma.views.sales import (SalesReturnView, SalesReturnListView, SalesReturnDeleteView,
                                   SalesReturnDetailAPIView, CustomerInvoicesAPIView,
                                   InvoiceItemsAPIView, ProductSalesHistoryAPIView, calculate_sale_summary)
from tenants.models import Tenant


class DailySaleReportViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='tester',
            user_type='tenant_owner',
            password='secret123',
        )
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            subdomain='testtenant',
            pharmacy_name='Test Pharmacy',
            address='Test Address',
            phone='1234567890',
            city='Test City',
            license_number='LIC-001',
            owner=self.user,
        )
        self.factory = RequestFactory()

    def test_invoice_summary_keeps_exact_total_without_forced_rupee_rounding(self):
        summary = calculate_sale_summary(2634.75, 131.74, 0)

        self.assertEqual(summary['sub_total'], Decimal('2634.75'))
        self.assertEqual(summary['tax_amount'], Decimal('131.74'))
        self.assertEqual(summary['total_amount'], Decimal('2766.49'))
        self.assertEqual(summary['round_off'], Decimal('0.00'))

    def test_daily_sale_report_subtracts_returns_from_total_amount(self):
        sale = SaleInvoice.objects.create(
            tenant=self.tenant,
            invoice_number='INV-0001',
            user=self.user,
            sub_total=Decimal('1000.00'),
            tax_amount=Decimal('0.00'),
            discount_amount=Decimal('0.00'),
            total_amount=Decimal('1000.00'),
        )
        SalesReturn.objects.create(
            tenant=self.tenant,
            sale_invoice=sale,
            return_qty=1,
            return_amount=Decimal('200.00'),
        )

        old_sale = SaleInvoice.objects.create(
            tenant=self.tenant,
            invoice_number='INV-0002',
            user=self.user,
            sub_total=Decimal('500.00'),
            tax_amount=Decimal('0.00'),
            discount_amount=Decimal('0.00'),
            total_amount=Decimal('500.00'),
        )
        SaleInvoice.objects.filter(id=old_sale.id).update(created_at=timezone.now() - timedelta(days=1))
        old_sale.refresh_from_db()
        old_return = SalesReturn.objects.create(
            tenant=self.tenant,
            sale_invoice=old_sale,
            return_qty=1,
            return_amount=Decimal('150.00'),
        )
        old_return.return_at = timezone.now() - timedelta(days=1)
        old_return.save(update_fields=['return_at'])

        request = self.factory.get('/')
        request.user = self.user
        request.tenant = self.tenant

        view = DailySaleReportView()
        context = view.get_report_context(request, sale.created_at.date(), 'all')

        self.assertEqual(context['daily_stats']['gross_total_amount'], Decimal('1000.00'))
        self.assertEqual(context['daily_stats']['total_return_amount'], Decimal('200.00'))
        self.assertEqual(context['daily_stats']['total_amount'], Decimal('800.00'))


class SalesReturnFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='return-tester',
            user_type='tenant_owner',
            password='secret123',
        )
        self.tenant = Tenant.objects.create(
            name='Return Test Tenant',
            subdomain='returntest',
            pharmacy_name='Return Test Pharmacy',
            address='Test Address',
            phone='1234567890',
            city='Test City',
            license_number='LIC-RETURN-001',
            owner=self.user,
        )
        self.factory = RequestFactory()
        self.setup = GeneralSetup.objects.create(tenant=self.tenant, sale_type='strip')
        self.product = Products.objects.create(
            tenant=self.tenant,
            product_name='Test Medicine',
            product_hsn_code='3004',
            conversion_factor=10,
        )
        self.batch = StockBatch.objects.create(
            tenant=self.tenant,
            product=self.product,
            batch_number='BATCH-1',
            expiry_date=timezone.localdate() + timedelta(days=365),
            purchase_price=Decimal('100.00'),
            mrp=Decimal('200.00'),
            initial_quantity=30,
            current_quantity=10,
        )
        self.invoice = SaleInvoice.objects.create(
            tenant=self.tenant,
            invoice_number='INV-RETURN-001',
            user=self.user,
            total_amount=Decimal('400.00'),
        )
        self.sale_item = SaleItem.objects.create(
            tenant=self.tenant,
            sale_invoice=self.invoice,
            product=self.product,
            batch_number=self.batch.batch_number,
            quantity=2,
            unit_price=Decimal('200.00'),
            total_amount=Decimal('400.00'),
        )

    def post_return(self, data):
        request = self.factory.post('/pos/returns/create/', data)
        request.tenant = self.tenant
        request.user = self.user
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)
        return SalesReturnView().post(request)

    def test_invoice_return_enforces_remaining_quantity_and_converts_strip_stock(self):
        response = self.post_return({
            'action': 'process_return',
            'invoice_id': str(self.invoice.id),
            'return_items[]': [str(self.sale_item.id)],
            'return_quantities[]': ['1'],
            'return_reasons[]': [''],
        })
        self.assertEqual(response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 20)

        self.post_return({
            'action': 'process_return',
            'invoice_id': str(self.invoice.id),
            'return_items[]': [str(self.sale_item.id)],
            'return_quantities[]': ['2'],
            'return_reasons[]': [''],
        })
        self.assertEqual(SalesReturn.objects.filter(tenant=self.tenant).count(), 1)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 20)

    def test_edit_and_delete_reverse_strip_stock_with_conversion_factor(self):
        return_record = SalesReturn.objects.create(
            tenant=self.tenant,
            sale_invoice=self.invoice,
            return_qty=1,
            return_amount=Decimal('200.00'),
        )
        return_item = SalesReturnItem.objects.create(
            tenant=self.tenant,
            sales_return=return_record,
            sale_item=self.sale_item,
            returned_quantity=1,
        )
        StockBatch.objects.filter(id=self.batch.id).update(current_quantity=20)

        self.post_return({
            'action': 'update_return',
            'return_id': str(return_record.id),
            'return_item_ids[]': [str(return_item.id)],
            'return_quantities[]': ['2'],
            'return_reasons[]': [''],
        })
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 30)

        self.post_return({
            'action': 'delete_return',
            'return_id': str(return_record.id),
        })
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)
        self.assertFalse(SalesReturn.objects.filter(id=return_record.id).exists())

    def test_quick_return_rejects_products_without_matching_sales(self):
        self.sale_item.delete()
        response = self.post_return({
            'action': 'quick_return',
            'product_id[]': [str(self.product.id)],
            'batch_number[]': [self.batch.batch_number],
            'return_qty[]': ['1'],
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SalesReturn.objects.filter(tenant=self.tenant).exists())
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

    def test_quick_return_success_creates_records_and_restores_stock(self):
        response = self.post_return({
            'action': 'quick_return',
            'product_id[]': [str(self.product.id)],
            'batch_number[]': [self.batch.batch_number],
            'return_qty[]': ['1'],
            'patient_name': 'Walk-in Customer',
        })
        self.assertEqual(response.status_code, 302)
        ret = SalesReturn.objects.filter(tenant=self.tenant).first()
        self.assertIsNotNone(ret)
        self.assertEqual(ret.return_qty, 1)
        self.assertEqual(ret.return_amount, Decimal('200.00'))
        self.batch.refresh_from_db()
        # initial was 10, returned 1 strip (conversion_factor=10) -> current_quantity = 20
        self.assertEqual(self.batch.current_quantity, 20)

    def test_quick_return_with_patient_name_fallback_to_unreturned_sales(self):
        response = self.post_return({
            'action': 'quick_return',
            'product_id[]': [str(self.product.id)],
            'batch_number[]': [self.batch.batch_number],
            'return_qty[]': ['1'],
            'patient_name': 'New Customer Name',
        })
        self.assertEqual(response.status_code, 302)
        ret = SalesReturn.objects.filter(tenant=self.tenant).first()
        self.assertIsNotNone(ret)
        self.assertEqual(ret.customer_name, 'New Customer Name')

    def test_customer_invoices_api_search_by_invoice_number(self):
        request = self.factory.get(f'/api/sales/customer-invoices/?search={self.invoice.invoice_number}')
        request.tenant = self.tenant
        request.user = self.user
        response = CustomerInvoicesAPIView().get(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(len(data['invoices']), 1)
        self.assertEqual(data['invoices'][0]['invoice_number'], self.invoice.invoice_number)
        self.assertEqual(data['invoices'][0]['items_count'], 1)

    def test_invoice_items_api(self):
        request = self.factory.get(f'/api/sales/invoice-items/?invoice_id={self.invoice.id}')
        request.tenant = self.tenant
        request.user = self.user
        response = InvoiceItemsAPIView().get(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['max_return_quantity'], 2)

    def test_sales_return_detail_api(self):
        return_record = SalesReturn.objects.create(
            tenant=self.tenant,
            sale_invoice=self.invoice,
            return_qty=1,
            return_amount=Decimal('200.00'),
        )
        SalesReturnItem.objects.create(
            tenant=self.tenant,
            sales_return=return_record,
            sale_item=self.sale_item,
            returned_quantity=1,
            return_reason='Test reason',
        )
        request = self.factory.get(f'/api/sales/returns/{return_record.id}/')
        request.tenant = self.tenant
        request.user = self.user
        response = SalesReturnDetailAPIView().get(request, return_id=return_record.id)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['return_data']['return_inv_no'], return_record.return_inv_no)
        self.assertEqual(len(data['return_data']['items']), 1)

    def test_sales_return_delete_view_restores_inventory(self):
        return_record = SalesReturn.objects.create(
            tenant=self.tenant,
            sale_invoice=self.invoice,
            return_qty=1,
            return_amount=Decimal('200.00'),
        )
        SalesReturnItem.objects.create(
            tenant=self.tenant,
            sales_return=return_record,
            sale_item=self.sale_item,
            returned_quantity=1,
        )
        StockBatch.objects.filter(id=self.batch.id).update(current_quantity=20)

        request = self.factory.post(f'/pos/returns/delete/{return_record.id}/')
        request.tenant = self.tenant
        request.user = self.user
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.save()
        request._messages = FallbackStorage(request)

        response = SalesReturnDeleteView().post(request, return_id=return_record.id)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(SalesReturn.objects.filter(id=return_record.id).exists())
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.current_quantity, 10)

    def test_sales_return_list_view_renders_successfully(self):
        SalesReturn.objects.create(
            tenant=self.tenant,
            sale_invoice=self.invoice,
            return_qty=1,
            return_amount=Decimal('200.00'),
        )
        request = self.factory.get('/pos/returns/')
        request.tenant = self.tenant
        request.user = self.user
        response = SalesReturnListView().get(request)
        self.assertEqual(response.status_code, 200)

    def test_product_sales_history_api_limits_to_five_and_has_more(self):
        # Create 6 sale invoices with items for this product
        for i in range(6):
            inv = SaleInvoice.objects.create(
                tenant=self.tenant,
                invoice_number=f'INV-HIST-{i}',
                patient_name=f'Patient {i}',
                user=self.user,
                total_amount=Decimal('200.00'),
            )
            SaleItem.objects.create(
                tenant=self.tenant,
                sale_invoice=inv,
                product=self.product,
                batch_number='BATCH-1',
                quantity=2,
                unit_price=Decimal('100.00'),
                total_amount=Decimal('200.00'),
            )

        # Default limit=5
        request = self.factory.get(f'/api/sales/product-sales-history/?product_id={self.product.id}')
        request.tenant = self.tenant
        request.user = self.user
        response = ProductSalesHistoryAPIView().get(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['total_count'], 7)  # 1 initial + 6 new = 7
        self.assertEqual(len(data['sales']), 5)
        self.assertTrue(data['has_more'])
        self.assertEqual(data['remaining_count'], 2)

        # Query all records
        request_all = self.factory.get(f'/api/sales/product-sales-history/?product_id={self.product.id}&limit=all')
        request_all.tenant = self.tenant
        request_all.user = self.user
        response_all = ProductSalesHistoryAPIView().get(request_all)
        data_all = json.loads(response_all.content)
        self.assertEqual(len(data_all['sales']), 7)
        self.assertFalse(data_all['has_more'])
        self.assertEqual(data_all['remaining_count'], 0)
