from decimal import Decimal
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from easypharma.models.sales import SaleInvoice, SalesReturn
from easypharma.views.reports import DailySaleReportView
from tenants.models import Tenant


class DailySaleReportViewTests(TestCase):
    def setUp(self):
        self.tenant = Tenant.objects.create(
            name='Test Tenant',
            subdomain='testtenant',
            pharmacy_name='Test Pharmacy',
            address='Test Address',
            phone='1234567890',
            city='Test City',
            license_number='LIC-001',
        )
        self.user = get_user_model().objects.create_user(
            username='tester',
            email='tester@example.com',
            password='secret123',
        )
        self.factory = RequestFactory()

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
            created_at=(timezone.now() - timedelta(days=1)),
        )
        old_return = SalesReturn.objects.create(
            tenant=self.tenant,
            sale_invoice=old_sale,
            return_qty=1,
            return_amount=Decimal('150.00'),
        )
        old_return.return_at = timezone.now()
        old_return.save(update_fields=['return_at'])

        request = self.factory.get('/')
        request.user = self.user
        request.tenant = self.tenant

        view = DailySaleReportView()
        context = view.get_report_context(request, sale.created_at.date(), 'all')

        self.assertEqual(context['daily_stats']['gross_total_amount'], Decimal('1000.00'))
        self.assertEqual(context['daily_stats']['total_return_amount'], Decimal('200.00'))
        self.assertEqual(context['daily_stats']['total_amount'], Decimal('800.00'))
