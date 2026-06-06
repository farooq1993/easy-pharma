import logging
from django.db.models import Prefetch
from django.views import View
from django.shortcuts import render
from easypharma.models.stock import StockBatch
from easypharma.models.Items import Products, ProductSchedule
from easypharma.models.purchase_invoice import PurchaseInvoice, PurchaseItem
from easypharma.models.sales import SaleInvoice, SaleItem
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Q, Count
from django.utils.timezone import now
from datetime import datetime, timedelta
from decimal import Decimal

logger = logging.getLogger('easypharma.reports')

import os
import csv
from io import BytesIO
from django.conf import settings
from django.template.loader import get_template
from django.http import HttpResponse


def link_callback(uri, rel):
    if uri.startswith(settings.STATIC_URL):
        path = os.path.join(settings.STATIC_ROOT, uri.replace(settings.STATIC_URL, ""))
        if not os.path.exists(path):
            for static_dir in getattr(settings, 'STATICFILES_DIRS', []):
                p = os.path.join(static_dir, uri.replace(settings.STATIC_URL, ""))
                if os.path.exists(p):
                    path = p
                    break
        return path
    elif uri.startswith(settings.MEDIA_URL):
        path = os.path.join(settings.MEDIA_ROOT, uri.replace(settings.MEDIA_URL, ""))
        return path
    return uri


def render_to_pdf(request, template_src, context_dict={}, filename="report.pdf"):
    try:
        from weasyprint import HTML
    except Exception as err:
        logger.warning('WeasyPrint import failed: %s', err)
        return HttpResponse(
            "PDF export is unavailable because WeasyPrint is not installed or its native libraries are missing.",
            content_type='text/plain',
            status=503
        )

    context_dict = dict(context_dict)
    context_dict['is_pdf'] = True
    template = get_template(template_src)
    html_string = template.render(context_dict)

    try:
        html = HTML(string=html_string, base_url=request.build_absolute_uri('/'))
        pdf_data = html.write_pdf()
    except Exception as err:
        logger.error('WeasyPrint PDF generation failed: %s', err, exc_info=True)
        return HttpResponse(
            "PDF export is unavailable because the server is missing required WeasyPrint libraries.",
            content_type='text/plain',
            status=503
        )

    response = HttpResponse(pdf_data, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def export_sales_csv(request, sales, filename='sales_report.csv'):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)

    writer.writerow([
        'Invoice Number', 'Date', 'Customer/Patient', 'Sale Type',
        'Product', 'Schedule', 'Quantity', 'Unit Price', 'Tax Amount',
        'Item Total', 'Subtotal', 'Discount', 'Total', 'Payment Mode', 'Time'
    ])

    items = SaleItem.objects.filter(
        tenant=request.tenant,
        sale_invoice__in=sales
    ).select_related('sale_invoice', 'product', 'product__product_schedule').order_by('sale_invoice__created_at')

    for item in items:
        invoice = item.sale_invoice
        customer_name = invoice.patient_name or (invoice.customer.name if invoice.customer else 'N/A')
        writer.writerow([
            invoice.invoice_number,
            invoice.created_at.strftime('%Y-%m-%d'),
            customer_name,
            invoice.sale_type,
            item.product.product_name,
            item.product.product_schedule.schedule_name if item.product.product_schedule else '',
            item.quantity,
            float(item.sale_price),
            float(item.tax_amount or 0),
            float(item.total_amount),
            float(invoice.sub_total or 0),
            float(invoice.discount_amount or 0),
            float(invoice.total_amount or 0),
            invoice.payment_mode,
            invoice.created_at.strftime('%H:%M:%S'),
        ])

    return response


class StockReportView(View):
    template_name = 'reports/stock_report.html'

    def get(self, request):
        # Aggregate stock by product
        stocks = StockBatch.objects.filter(tenant=request.tenant, current_quantity__gt=0).select_related('product')
        
        # Also group by product for a summary
        from django.db.models import ExpressionWrapper, DecimalField
        product_summary = StockBatch.objects.filter(tenant=request.tenant).values(
            'product__product_name', 'product__product_packing', 'product__conversion_factor'
        ).annotate(
            total_stock=Sum('current_quantity'),
            total_value=Sum(
                ExpressionWrapper(
                    F('current_quantity') * (F('purchase_price') / F('product__conversion_factor')),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        ).order_by('product__product_name')

        total_value = sum(item['total_value'] for item in product_summary)
        
        context = {
            'stocks': stocks,
            'summary': product_summary,
            'total_value': total_value
        }
        
        if request.GET.get('pdf') == '1':
            return render_to_pdf(self.template_name, context, filename="stock_report.pdf")

        return render(request, self.template_name, context)


# ========== NEW REPORTS ==========

class DailySaleReportView(View):
    """Daily Sale Report - Show sales data for a specific date"""
    template_name = 'reports/daily_sale_report.html'

    def get(self, request):
        selected_schedule = request.GET.get('schedule', 'all')
        # Get date from request or use today
        date_str = request.GET.get('date', now().date())
        if isinstance(date_str, str):
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                date_obj = now().date()
        else:
            date_obj = date_str

        logger.debug('DailySaleReportView.get date=%s schedule=%s tenant=%s user=%s', date_obj, selected_schedule, request.tenant, request.user)

        # Get sales for the day
        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__date=date_obj
        ).select_related('customer', 'user')

        if selected_schedule and selected_schedule.lower() != 'all':
            sales = sales.filter(items__product__product_schedule__schedule_name=selected_schedule).distinct()

        # Calculate totals
        daily_stats = sales.aggregate(
            total_sales=Count('id'),
            total_amount=Sum('total_amount'),
            total_tax=Sum('tax_amount'),
            total_discount=Sum('discount_amount'),
            subtotal=Sum('sub_total')
        )

        # Counter Sales vs Prescription Sales breakdown
        counter_stats = sales.filter(sale_type='Counter').aggregate(
            count=Count('id'),
            amount=Sum('total_amount')
        )
        prescription_stats = sales.filter(sale_type='Prescription').aggregate(
            count=Count('id'),
            amount=Sum('total_amount')
        )

        # Payment mode breakdown
        payment_breakdown = sales.values('payment_mode').annotate(
            count=Count('id'),
            amount=Sum('total_amount')
        )

        # Top products sold
        top_products = SaleItem.objects.filter(
            tenant=request.tenant,
            sale_invoice__created_at__date=date_obj
        )
        if selected_schedule and selected_schedule.lower() != 'all':
            top_products = top_products.filter(product__product_schedule__schedule_name=selected_schedule)

        top_products = top_products.values('product__product_name').annotate(
            qty_sold=Sum('quantity'),
            total_revenue=Sum('total_amount')
        ).order_by('-total_revenue')[:10]

        report_schedules = ProductSchedule.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('schedule_name')

        context = {
            'date': date_obj,
            'sales': sales,
            'daily_stats': daily_stats,
            'counter_stats': counter_stats,
            'prescription_stats': prescription_stats,
            'payment_breakdown': payment_breakdown,
            'top_products': top_products,
            'report_schedules': report_schedules,
            'selected_schedule': selected_schedule,
        }

        if request.GET.get('csv') == '1':
            filename = f"daily_sale_report_{date_obj}.csv"
            return export_sales_csv(request, sales, filename=filename)

        if request.GET.get('pdf') == '1':
            return render_to_pdf(request, self.template_name, context, filename=f"daily_sale_report_{date_obj}.pdf")

        return render(request, self.template_name, context)


class HalfYearlySaleReportView(View):
    """H1/H2 Sale Report - Show sales data for a half year (6 months)"""
    template_name = 'reports/half_yearly_report.html'

    def get(self, request):
        selected_schedule = request.GET.get('schedule', 'all')
        # Determine whether a custom date range is requested
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')
        date_range_label = None

        start_date = None
        end_date = None
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
                if start_date > end_date:
                    start_date, end_date = end_date, start_date
                date_range_label = f"{start_date.strftime('%d %b %Y')} - {end_date.strftime('%d %b %Y')}"
            except ValueError:
                start_date = None
                end_date = None

        half = request.GET.get('half', 'current')
        year = int(request.GET.get('year', now().year))

        today = now().date()
        current_month = today.month

        if start_date is None or end_date is None:
            if half == 'H1' or (half == 'current' and current_month <= 6):
                start_month = 1
                end_month = 6
                half_label = f"H1 {year} (Jan - Jun)"
            else:
                start_month = 7
                end_month = 12
                half_label = f"H2 {year} (Jul - Dec)"

            start_date = datetime(year, start_month, 1).date()
            last_day = datetime(year, end_month, 1).replace(day=28) + timedelta(days=4)
            last_day = last_day.replace(day=1) - timedelta(days=1)
            end_date = last_day.date()
        else:
            half_label = date_range_label

        logger.debug('HalfYearlySaleReportView.get start_date=%s end_date=%s schedule=%s tenant=%s user=%s', start_date, end_date, selected_schedule, request.tenant, request.user)

        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )
        if selected_schedule and selected_schedule.lower() != 'all':
            sales = sales.filter(items__product__product_schedule__schedule_name=selected_schedule).distinct()

        monthly_data = []
        current_month_date = datetime(start_date.year, start_date.month, 1).date()
        while current_month_date <= end_date:
            month_sales = sales.filter(
                created_at__year=current_month_date.year,
                created_at__month=current_month_date.month
            )
            month_name = current_month_date.strftime('%B')

            stats = month_sales.aggregate(
                total=Sum('total_amount'),
                count=Count('id'),
                tax=Sum('tax_amount'),
                discount=Sum('discount_amount')
            )

            avg_sale = stats['total'] / stats['count'] if stats['count'] and stats['count'] > 0 else Decimal('0')
            monthly_data.append({
                'month': month_name,
                'month_num': current_month_date.month,
                'sales_count': stats['count'] or 0,
                'total': stats['total'] or Decimal('0'),
                'tax': stats['tax'] or Decimal('0'),
                'discount': stats['discount'] or Decimal('0'),
                'avg_sale': avg_sale,
            })
            next_month = current_month_date.replace(day=28) + timedelta(days=4)
            current_month_date = next_month.replace(day=1)

        # Half year totals
        h_stats = sales.aggregate(
            total_sales=Count('id'),
            total_amount=Sum('total_amount'),
            total_tax=Sum('tax_amount'),
            total_discount=Sum('discount_amount'),
            subtotal=Sum('sub_total')
        )
        
        # Add average per transaction
        if h_stats['total_sales'] and h_stats['total_sales'] > 0:
            h_stats['avg_amount'] = h_stats['total_amount'] / h_stats['total_sales']
        else:
            h_stats['avg_amount'] = Decimal('0')

        # Top customers
        top_customers = sales.values('customer__name').annotate(
            purchases=Count('id'),
            amount=Sum('total_amount')
        ).order_by('-amount')[:10]
        
        # Add average per purchase
        for customer in top_customers:
            customer['avg_amount'] = customer['amount'] / customer['purchases'] if customer['purchases'] > 0 else 0

        # Sale details for each matching invoice (useful for patient/date-level review)
        sale_details = sales.select_related('customer').prefetch_related(
                        Prefetch(
                            'items',
                            queryset=SaleItem.objects.select_related(
                                'product',
                                'product__product_schedule'
                            )
                        )
                    ).order_by('-created_at')
        

        # Product-level summary for selected schedule / half-year period
        product_summary = SaleItem.objects.filter(
            tenant=request.tenant,
            sale_invoice__in=sales
        ).values(
            'product__product_name',
            'product__product_schedule__schedule_name'
        ).annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total_amount')
        ).order_by('-quantity_sold')
        
        report_schedules = ProductSchedule.objects.filter(Q(tenant=request.tenant) | Q(tenant__isnull=True)).order_by('schedule_name')

        context = {
            'half_label': half_label,
            'half': half,
            'year': year,
            'start_date': start_date,
            'end_date': end_date,
            'monthly_data': monthly_data,
            'h_stats': h_stats,
            'top_customers': top_customers,
            'sale_details': sale_details,
            'product_summary': product_summary,
            'report_schedules': report_schedules,
            'selected_schedule': selected_schedule,
        }
        if request.GET.get('csv') == '1':
            filename_suffix = selected_schedule if selected_schedule != 'all' else 'all'
            filename = f"half_yearly_sale_report_{filename_suffix}_{start_date}_{end_date}.csv"
            return export_sales_csv(request, sales, filename=filename)

        if request.GET.get('pdf') == '1':
            fn = f"sale_report_{selected_schedule}.pdf" if selected_schedule != 'all' else "sale_report.pdf"
            return render_to_pdf(request, self.template_name, context, filename=fn)

        return render(request, self.template_name, context)


class ProfitReportView(View):
    """Profit Report - Date-wise profit analysis"""
    template_name = 'reports/profit_report.html'

    def get(self, request):
        # Get date range from request
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')

        # Default to last 30 days
        end_date = now().date()
        start_date = end_date - timedelta(days=30)

        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass

        # Sales in period
        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )

        # Cost of goods sold and profit based on MRP minus purchase price
        sale_items = SaleItem.objects.filter(
            tenant=request.tenant,
            sale_invoice__created_at__date__gte=start_date,
            sale_invoice__created_at__date__lte=end_date
        ).select_related('sale_invoice', 'product')

        cost_by_date = {}
        profit_by_date = {}
        for item in sale_items:
            sale_date = item.sale_invoice.created_at.date()
            batch_cost = Decimal('0')
            batch_mrp = Decimal('0')
            if item.batch_number:
                batch = StockBatch.objects.filter(
                    tenant=request.tenant,
                    product=item.product,
                    batch_number=item.batch_number
                ).first()
                if batch:
                    if batch.purchase_price is not None:
                        batch_cost = batch.purchase_price
                    if batch.mrp is not None:
                        batch_mrp = batch.mrp

            conv_factor = Decimal(str(item.product.conversion_factor or 1))
            unit_cost = batch_cost / conv_factor
            item_cost = unit_cost * item.quantity
            cost_by_date[sale_date] = cost_by_date.get(sale_date, Decimal('0')) + item_cost
            sale_value = item.total_amount or Decimal('0')
            profit_by_date[sale_date] = (
                            profit_by_date.get(sale_date, Decimal('0'))
                            + (sale_value - item_cost)
                        )

        # Daily profit data
        daily_profit = []
        current_date = start_date
        while current_date <= end_date:
            day_sales = sales.filter(created_at__date=current_date).aggregate(
                total=Sum('total_amount'),
                subtotal=Sum('sub_total')
            )

            revenue = day_sales['total'] or Decimal('0')
            cost = cost_by_date.get(current_date, Decimal('0'))
            profit = profit_by_date.get(current_date, Decimal('0'))

            daily_profit.append({
                'date': current_date,
                'revenue': revenue,
                'cost': cost,
                'profit': profit,
                'tax': (day_sales['total'] or Decimal('0')) - (day_sales['subtotal'] or Decimal('0')),
            })

            current_date += timedelta(days=1)

        # Summary stats
        total_revenue = sum(d['revenue'] for d in daily_profit)
        total_cost = sum(d['cost'] for d in daily_profit)
        total_profit = sum(d['profit'] for d in daily_profit)
        profit_margin = ((total_profit / total_revenue) * 100 if total_revenue > 0 else 0)

        context = {
            'start_date': start_date,
            'end_date': end_date,
            'daily_profit': daily_profit,
            'total_revenue': total_revenue,
            'total_cost': total_cost,
            'total_profit': total_profit,
            'profit_margin': round(profit_margin, 2),
        }
        if request.GET.get('pdf') == '1':
            return render_to_pdf(self.template_name, context, filename="profit_report.pdf")

        return render(request, self.template_name, context)


class GSTReportView(View):
    """GST Report - GST as per Indian GST Law"""
    template_name = 'reports/gst_report.html'

    def get(self, request):
        # Get month and year from request or use current
        month = int(request.GET.get('month', now().month))
        year = int(request.GET.get('year', now().year))

        # Get sales for the month
        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__year=year,
            created_at__month=month
        ).prefetch_related('items')

        # Get purchases for the month
        purchases = PurchaseInvoice.objects.filter(
            tenant=request.tenant,
            created_at__year=year,
            created_at__month=month
        ).prefetch_related('items')

        # Calculate GST data
        sale_items = SaleItem.objects.filter(
            tenant=request.tenant,
            sale_invoice__created_at__year=year,
            sale_invoice__created_at__month=month
        )

        purchase_items = PurchaseItem.objects.filter(
            tenant=request.tenant,
            purchase_invoice__created_at__year=year,
            purchase_invoice__created_at__month=month
        )

        # Group by GST rate
        sales_by_gst = sale_items.values('tax_percentage').annotate(
                        taxable_value=Sum(
                            ExpressionWrapper(
                                F('quantity') * F('unit_price'),
                                output_field=DecimalField(max_digits=12, decimal_places=2)
                            )
                        ),
                        tax_amount=Sum(
                            ExpressionWrapper(
                                (F('quantity') * F('unit_price') * F('tax_percentage')) / 100,
                                output_field=DecimalField(max_digits=12, decimal_places=2)
                            )
                        ),
                        total=Sum('total_amount')
                    ).order_by('tax_percentage')

        # Summary
        total_sales_value = sale_items.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('quantity') * F('unit_price'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['total'] or Decimal('0')

        total_sales_gst = sale_items.aggregate(
                            total=Sum(
                                ExpressionWrapper(
                                    (F('quantity') * F('unit_price') * F('tax_percentage')) / 100,
                                    output_field=DecimalField(max_digits=12, decimal_places=2)
                                )
                            )
                        )['total'] or Decimal('0')

        total_purchase_value = purchase_items.aggregate(
            total=Sum(
                ExpressionWrapper(
                    F('quantity') * F('purchase_price'),
                    output_field=DecimalField(max_digits=12, decimal_places=2)
                )
            )
        )['total'] or Decimal('0')

        purchases_by_gst = purchase_items.values('tax_percentage').annotate(
                            taxable_value=Sum(
                                ExpressionWrapper(
                                    F('quantity') * F('purchase_price'),
                                    output_field=DecimalField(max_digits=12, decimal_places=2)
                                )
                            ),
                            tax_amount=Sum(
                                ExpressionWrapper(
                                    (F('quantity') * F('purchase_price') * F('tax_percentage')) / 100,
                                    output_field=DecimalField(max_digits=12, decimal_places=2)
                                )
                            ),
                            total=Sum('total_amount')
                        ).order_by('tax_percentage')

        total_purchase_gst = purchase_items.aggregate(
                            total=Sum(
                                ExpressionWrapper(
                                    (F('quantity') * F('purchase_price') * F('tax_percentage')) / 100,
                                    output_field=DecimalField(max_digits=12, decimal_places=2)
                                )
                            )
                        )['total'] or Decimal('0')

        # GST Liability (Outward GST - Inward GST)
        gst_liability = total_sales_gst - total_purchase_gst

        # GST return filing info
        month_name = datetime(year, month, 1).strftime('%B %Y')

        context = {
            'month': month,
            'year': year,
            'month_name': month_name,
            'sales_by_gst': sales_by_gst,
            'purchases_by_gst': purchases_by_gst,
            'total_sales_value': total_sales_value,
            'total_sales_gst': total_sales_gst,
            'total_purchase_value': total_purchase_value,
            'total_purchase_gst': total_purchase_gst,
            'gst_liability': gst_liability,
            'pharmacy_gst': request.tenant.gst_number or 'N/A',
        }
        if request.GET.get('pdf') == '1':
            return render_to_pdf(self.template_name, context, filename=f"gst_report_{month}_{year}.pdf")

        return render(request, self.template_name, context)


class ProductHistoryView(View):
    template_name = 'reports/product_history.html'

    def get(self, request):
        from django.http import JsonResponse
        from django.shortcuts import redirect
        from django.contrib import messages
        from easypharma.models.purchase_invoice import PurchaseItem
        from easypharma.models.sales import SaleItem
        from easypharma.models.stock import StockBatch
        
        product_id = request.GET.get('product_id')
        if not product_id:
            return render(request, self.template_name)
        
        try:
            product = Products.objects.get(id=product_id, tenant=request.tenant)
        except Products.DoesNotExist:
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
                return JsonResponse({'error': 'Product not found'}, status=404)
            messages.error(request, 'Product not found.')
            return redirect('product_history')
        
        # Purchases:
        purchases = PurchaseItem.objects.filter(
            product=product,
            tenant=request.tenant
        ).select_related('purchase_invoice', 'purchase_invoice__supplier').order_by('-purchase_invoice__purchase_date')
        
        purchase_list = []
        total_purchased_qty = 0
        total_free_qty = 0
        total_purchase_val = Decimal('0')
        for item in purchases:
            total_purchased_qty += item.quantity
            total_free_qty += item.free_quantity or 0
            total_purchase_val += Decimal(str(item.quantity)) * Decimal(str(item.purchase_price))
            purchase_list.append({
                'date': item.purchase_invoice.purchase_date.strftime('%Y-%m-%d'),
                'invoice_number': item.purchase_invoice.invoice_number,
                'supplier_name': item.purchase_invoice.supplier.name if item.purchase_invoice.supplier else '—',
                'batch_number': item.batch_number,
                'expiry_date': item.expiry_date.strftime('%m/%Y') if item.expiry_date else '—',
                'quantity': item.quantity,
                'free_quantity': item.free_quantity or 0,
                'purchase_price': float(item.purchase_price),
                'total': float(Decimal(str(item.quantity)) * Decimal(str(item.purchase_price)))
            })
            
        # Sales:
        sales = SaleItem.objects.filter(
            product=product,
            tenant=request.tenant
        ).select_related('sale_invoice').order_by('-sale_invoice__created_at')
        
        sale_list = []
        total_sold_qty = 0
        total_sales_val = Decimal('0')
        for item in sales:
            total_sold_qty += item.quantity
            total_sales_val += Decimal(str(item.total_amount))
            sale_list.append({
                'date': item.sale_invoice.created_at.strftime('%Y-%m-%d %H:%M'),
                'invoice_number': item.sale_invoice.invoice_number,
                'patient_name': item.sale_invoice.patient_name or 'Walk-in',
                'batch_number': item.batch_number,
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'total': float(item.total_amount)
            })
            
        # Stocks:
        stocks = StockBatch.objects.filter(
            product=product,
            tenant=request.tenant
        ).order_by('expiry_date')
        
        stock_list = []
        current_stock = 0
        for b in stocks:
            current_stock += b.current_quantity
            stock_list.append({
                'batch_number': b.batch_number,
                'expiry_date': b.expiry_date.strftime('%m/%Y') if b.expiry_date else '—',
                'stock': b.current_quantity,
                'purchase_price': float(b.purchase_price) if b.purchase_price else 0.0,
                'sale_price': float(b.sale_price) if b.sale_price else 0.0,
                'mrp': float(b.mrp) if b.mrp else 0.0
            })
            
        avg_purchase_price = float(total_purchase_val / total_purchased_qty) if total_purchased_qty > 0 else 0.0
        avg_sale_price = float(total_sales_val / total_sold_qty) if total_sold_qty > 0 else 0.0
        
        data = {
            'product_name': product.product_name,
            'packing': product.product_packing or '—',
            'conversion_factor': product.conversion_factor,
            'total_purchased': total_purchased_qty,
            'total_free': total_free_qty,
            'total_sold': total_sold_qty,
            'current_stock': current_stock,
            'avg_purchase_price': round(avg_purchase_price, 2),
            'avg_sale_price': round(avg_sale_price, 2),
            'purchases': purchase_list,
            'sales': sale_list,
            'stocks': stock_list
        }
        
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
            return JsonResponse(data)
            
        context = {
            'product': product,
            'data': data
        }

        if request.GET.get('pdf') == '1':
            return render_to_pdf(self.template_name, context, filename=f"product_history_{product.product_name}.pdf")

        return render(request, self.template_name, context)


# ========== SCHEDULE H & NARCOTIC DRUG REGISTER ==========

class ScheduleHReportView(View):
    """
    Schedule H / H1 Drug Register — lists all sales of Schedule H/H1 drugs
    in a format suitable for statutory drug register submission.
    """
    template_name = 'reports/schedule_h_report.html'

    def get(self, request):
        schedule_type = request.GET.get('schedule_type', 'Schedule H')
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')

        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                start_date = now().date().replace(day=1)
        else:
            start_date = now().date().replace(day=1)

        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                end_date = now().date()
        else:
            end_date = now().date()

        logger.debug('ScheduleHReportView.get schedule=%s start=%s end=%s tenant=%s', schedule_type, start_date, end_date, request.tenant)

        # Get sale items for the selected schedule in the date range
        sale_items = SaleItem.objects.filter(
            tenant=request.tenant,
            product__product_schedule__schedule_name=schedule_type,
            sale_invoice__created_at__date__gte=start_date,
            sale_invoice__created_at__date__lte=end_date,
        ).select_related(
            'product',
            'product__product_schedule',
            'sale_invoice',
            'sale_invoice__customer',
        ).order_by('sale_invoice__created_at')

        # Build register rows
        register_rows = []
        serial = 1
        for item in sale_items:
            inv = item.sale_invoice
            register_rows.append({
                'sr': serial,
                'date': inv.created_at.strftime('%d/%m/%Y'),
                'invoice_no': inv.invoice_number,
                'patient_name': inv.patient_name or (inv.customer.name if inv.customer else 'Walk-in'),
                'patient_address': inv.patient_address or '—',
                'patient_phone': inv.patient_phone or '—',
                'doctor_name': inv.doctor_name or '—',
                'product_name': item.product.product_name,
                'packing': item.product.product_packing or '—',
                'batch_number': item.batch_number or '—',
                'expiry_date': item.expiry_date.strftime('%m/%Y') if item.expiry_date else '—',
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'total': float(item.total_amount),
                'payment_mode': inv.payment_mode,
                'sale_type': inv.sale_type,
            })
            serial += 1

        # Summary stats
        total_qty = sum(r['quantity'] for r in register_rows)
        total_value = sum(r['total'] for r in register_rows)

        # Available schedule types for filter
        schedule_choices = ProductSchedule.objects.filter(
            Q(tenant=request.tenant) | Q(tenant__isnull=True)
        ).order_by('schedule_name')

        context = {
            'schedule_type': schedule_type,
            'start_date': start_date,
            'end_date': end_date,
            'register_rows': register_rows,
            'total_qty': total_qty,
            'total_value': total_value,
            'schedule_choices': schedule_choices,
            'pharmacy': request.tenant,
        }

        if request.GET.get('pdf') == '1':
            fn = f"schedule_h_register_{schedule_type.replace(' ', '_')}_{start_date}_{end_date}.pdf"
            return render_to_pdf(self.template_name, context, filename=fn)

        return render(request, self.template_name, context)


class NarcoticDrugReportView(View):
    """
    Narcotic Drug Register — purchase & sale register for narcotic drugs
    (as required under NDPS Act).
    """
    template_name = 'reports/narcotic_drug_report.html'

    def get(self, request):
        start_date_str = request.GET.get('start_date')
        end_date_str = request.GET.get('end_date')

        if start_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            except ValueError:
                start_date = now().date().replace(day=1)
        else:
            start_date = now().date().replace(day=1)

        if end_date_str:
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                end_date = now().date()
        else:
            end_date = now().date()

        logger.debug('NarcoticDrugReportView.get start=%s end=%s tenant=%s', start_date, end_date, request.tenant)

        NARCOTIC_SCHEDULES = ['Narcotic', 'Schedule X', 'NDPS']

        # Purchase register
        purchase_items = PurchaseItem.objects.filter(
            tenant=request.tenant,
            product__product_schedule__schedule_name__in=NARCOTIC_SCHEDULES,
            purchase_invoice__purchase_date__gte=start_date,
            purchase_invoice__purchase_date__lte=end_date,
        ).select_related(
            'product',
            'product__product_schedule',
            'purchase_invoice',
            'purchase_invoice__supplier',
        ).order_by('purchase_invoice__purchase_date')

        purchase_rows = []
        p_serial = 1
        for item in purchase_items:
            inv = item.purchase_invoice
            purchase_rows.append({
                'sr': p_serial,
                'date': inv.purchase_date.strftime('%d/%m/%Y') if inv.purchase_date else '—',
                'voucher_no': inv.voucher_number or inv.invoice_number,
                'supplier_name': inv.supplier.name if inv.supplier else '—',
                'supplier_dl': inv.supplier.dl_number if inv.supplier and hasattr(inv.supplier, 'dl_number') else '—',
                'product_name': item.product.product_name,
                'packing': item.product.product_packing or '—',
                'batch_number': item.batch_number,
                'expiry_date': item.expiry_date.strftime('%m/%Y') if item.expiry_date else '—',
                'quantity': item.quantity,
                'free_quantity': item.free_quantity,
                'purchase_price': float(item.purchase_price),
                'total': float(item.total_amount),
                'schedule': item.product.product_schedule.schedule_name if item.product.product_schedule else '—',
            })
            p_serial += 1

        # Sale register
        sale_items = SaleItem.objects.filter(
            tenant=request.tenant,
            product__product_schedule__schedule_name__in=NARCOTIC_SCHEDULES,
            sale_invoice__created_at__date__gte=start_date,
            sale_invoice__created_at__date__lte=end_date,
        ).select_related(
            'product',
            'product__product_schedule',
            'sale_invoice',
            'sale_invoice__customer',
        ).order_by('sale_invoice__created_at')

        sale_rows = []
        s_serial = 1
        for item in sale_items:
            inv = item.sale_invoice
            sale_rows.append({
                'sr': s_serial,
                'date': inv.created_at.strftime('%d/%m/%Y'),
                'invoice_no': inv.invoice_number,
                'patient_name': inv.patient_name or (inv.customer.name if inv.customer else 'Walk-in'),
                'patient_address': inv.patient_address or '—',
                'doctor_name': inv.doctor_name or '—',
                'product_name': item.product.product_name,
                'packing': item.product.product_packing or '—',
                'batch_number': item.batch_number or '—',
                'expiry_date': item.expiry_date.strftime('%m/%Y') if item.expiry_date else '—',
                'quantity': item.quantity,
                'unit_price': float(item.unit_price),
                'total': float(item.total_amount),
                'schedule': item.product.product_schedule.schedule_name if item.product.product_schedule else '—',
            })
            s_serial += 1

        total_purchase_qty = sum(r['quantity'] for r in purchase_rows)
        total_purchase_val = sum(r['total'] for r in purchase_rows)
        total_sale_qty = sum(r['quantity'] for r in sale_rows)
        total_sale_val = sum(r['total'] for r in sale_rows)

        context = {
            'start_date': start_date,
            'end_date': end_date,
            'purchase_rows': purchase_rows,
            'sale_rows': sale_rows,
            'total_purchase_qty': total_purchase_qty,
            'total_purchase_val': total_purchase_val,
            'total_sale_qty': total_sale_qty,
            'total_sale_val': total_sale_val,
            'pharmacy': request.tenant,
        }

        if request.GET.get('pdf') == '1':
            fn = f"narcotic_drug_register_{start_date}_{end_date}.pdf"
            return render_to_pdf(self.template_name, context, filename=fn)

        return render(request, self.template_name, context)

