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
        
        return render(request, self.template_name, {
            'stocks': stocks,
            'summary': product_summary,
            'total_value': total_value
        })


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
            'payment_breakdown': payment_breakdown,
            'top_products': top_products,
            'report_schedules': report_schedules,
            'selected_schedule': selected_schedule,
        }
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

        # Purchase in period
        purchases = PurchaseInvoice.objects.filter(
            tenant=request.tenant,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )

        # Daily profit data
        daily_profit = []
        current_date = start_date
        while current_date <= end_date:
            day_sales = sales.filter(created_at__date=current_date).aggregate(
                total=Sum('total_amount'),
                subtotal=Sum('sub_total')
            )
            
            day_purchases = purchases.filter(created_at__date=current_date).aggregate(
                total=Sum('total_amount')
            )

            revenue = day_sales['subtotal'] or Decimal('0')
            cost = day_purchases['total'] or Decimal('0')
            profit = revenue - cost

            daily_profit.append({
                'date': current_date,
                'revenue': revenue,
                'cost': cost,
                'profit': profit,
                'tax': (day_sales['total'] or Decimal('0')) - revenue,
            })

            current_date += timedelta(days=1)

        # Summary stats
        total_revenue = sum(d['revenue'] for d in daily_profit)
        total_cost = sum(d['cost'] for d in daily_profit)
        total_profit = total_revenue - total_cost
        profit_margin = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

        context = {
            'start_date': start_date,
            'end_date': end_date,
            'daily_profit': daily_profit,
            'total_revenue': total_revenue,
            'total_cost': total_cost,
            'total_profit': total_profit,
            'profit_margin': round(profit_margin, 2),
        }
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
            
        return render(request, self.template_name, {
            'product': product,
            'data': data
        })


