from django.views import View
from django.shortcuts import render
from easypharma.models.stock import StockBatch
from easypharma.models.Items import Products
from easypharma.models.purchase_invoice import PurchaseInvoice, PurchaseItem
from easypharma.models.sales import SaleInvoice, SaleItem
from django.db.models import Sum, F, DecimalField, ExpressionWrapper, Q, Count
from django.utils.timezone import now
from datetime import datetime, timedelta
from decimal import Decimal

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
        # Get date from request or use today
        date_str = request.GET.get('date', now().date())
        if isinstance(date_str, str):
            try:
                date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                date_obj = now().date()
        else:
            date_obj = date_str

        # Get sales for the day
        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__date=date_obj
        ).select_related('customer', 'user')

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
        ).values('product__product_name').annotate(
            qty_sold=Sum('quantity'),
            total_revenue=Sum('total_amount')
        ).order_by('-total_revenue')[:10]

        context = {
            'date': date_obj,
            'sales': sales,
            'daily_stats': daily_stats,
            'payment_breakdown': payment_breakdown,
            'top_products': top_products,
        }
        return render(request, self.template_name, context)


class HalfYearlySaleReportView(View):
    """H1/H2 Sale Report - Show sales data for a half year (6 months)"""
    template_name = 'reports/half_yearly_report.html'

    def get(self, request):
        # Get half year from request (H1=Jan-Jun, H2=Jul-Dec) or current half
        half = request.GET.get('half', 'current')
        year = int(request.GET.get('year', now().year))

        today = now().date()
        current_month = today.month

        # Determine which half
        if half == 'H1' or (half == 'current' and current_month <= 6):
            start_month = 1
            end_month = 6
            half_label = f"H1 {year} (Jan - Jun)"
        else:
            start_month = 7
            end_month = 12
            half_label = f"H2 {year} (Jul - Dec)"

        # Filter sales for the half year
        sales = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__year=year,
            created_at__month__gte=start_month,
            created_at__month__lte=end_month
        )

        # Monthly breakdown
        monthly_data = []
        for month in range(start_month, end_month + 1):
            month_sales = sales.filter(created_at__month=month)
            month_name = datetime(year, month, 1).strftime('%B')
            
            stats = month_sales.aggregate(
                total=Sum('total_amount'),
                count=Count('id'),
                tax=Sum('tax_amount'),
                discount=Sum('discount_amount')
            )
            
            avg_sale = stats['total'] / stats['count'] if stats['count'] and stats['count'] > 0 else Decimal('0')
            
            monthly_data.append({
                'month': month_name,
                'month_num': month,
                'sales_count': stats['count'] or 0,
                'total': stats['total'] or Decimal('0'),
                'tax': stats['tax'] or Decimal('0'),
                'discount': stats['discount'] or Decimal('0'),
                'avg_sale': avg_sale,
            })

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

        context = {
            'half_label': half_label,
            'half': half,
            'year': year,
            'monthly_data': monthly_data,
            'h_stats': h_stats,
            'top_customers': top_customers,
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

