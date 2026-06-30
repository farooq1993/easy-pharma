from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, permission_required, login_required
from django.views.decorators.http import require_http_methods
from easypharma.models import User
from django.contrib import messages
from easypharma.models.sales import SaleInvoice, Customer, SaleItem
from easypharma.models.Items import Products
from django.db.models import Sum, Count, Q, F, DecimalField,ExpressionWrapper
from django.db.models.functions import TruncDate
from datetime import date, timedelta
from tenants.models import Tenant
import uuid
import json


@login_required
def home_view(request):
    period = request.GET.get('period', 'today')
    today = date.today()
    if not request.tenant:
        messages.warning(request, "No pharmacy linked to your account. Please assign one in Admin.")
    
    # Determine date range based on period
    if period == 'month':
        start_date = today.replace(day=1)
        period_label = 'This Month'
    elif period == 'year':
        start_date = today.replace(month=1, day=1)
        period_label = 'This Year'
    else:
        start_date = today
        period_label = 'Today'

    # Period Stats
    period_revenue = SaleInvoice.objects.filter(
        tenant=request.tenant, 
        created_at__date__gte=start_date,
        created_at__date__lte=today
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0

    period_transactions = SaleInvoice.objects.filter(
        tenant=request.tenant, 
        created_at__date__gte=start_date,
        created_at__date__lte=today
    ).count()

    new_customers_period = Customer.objects.filter(
        tenant=request.tenant,
        created_at__date__gte=start_date,
        created_at__date__lte=today
    ).count()

    # Basic Stats
    today_revenue = SaleInvoice.objects.filter(tenant=request.tenant, created_at__date=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_customers = Customer.objects.filter(tenant=request.tenant).count()
    prescriptions_count = SaleInvoice.objects.filter(tenant=request.tenant, created_at__date=today).count()
    
    # Expiry Alert (within 90 days)
    from easypharma.models.stock import StockBatch
    expiry_limit = today + timedelta(days=90)
    near_expiry_batches = StockBatch.objects.filter(
        tenant=request.tenant,
        expiry_date__lte=expiry_limit,
        expiry_date__gte=today,
        current_quantity__gt=0
    ).select_related('product').order_by('expiry_date')[:10]
    
    # Low stock logic (products with total stock < 50 units)
    from django.db.models import Sum as DbSum
    low_stock_count = StockBatch.objects.filter(tenant=request.tenant).values('product').annotate(total=DbSum('current_quantity')).filter(total__lt=50).count()
    
    # Monthly Revenue Trend (Last 12 months)
    revenue_trend = []
    labels_revenue = []
    for i in range(11, -1, -1):
        month_start_trend = today.replace(day=1) - timedelta(days=i*30)
        month_start_trend = month_start_trend.replace(day=1)
        month_end_trend = (month_start_trend + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        
        monthly_revenue = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__date__gte=month_start_trend,
            created_at__date__lte=month_end_trend
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        revenue_trend.append(float(monthly_revenue))
        labels_revenue.append(month_start_trend.strftime('%b'))
    
    # Sales by Payment Method (Last 30 days)
    thirty_days_ago = today - timedelta(days=30)
    payment_methods = SaleInvoice.objects.filter(
        tenant=request.tenant,
        created_at__date__gte=thirty_days_ago
    ).values('payment_mode').annotate(count=Count('id'), total=Sum('total_amount'))
    
    payment_labels = []
    payment_data = []
    payment_colors = {'Cash': '#1cc88a', 'Card': '#4e73df', 'UPI': '#36b9cc', 'Credit': '#f6c23e'}
    for method in payment_methods:
        payment_labels.append(method['payment_mode'])
        payment_data.append(float(method['total'] or 0))
    
    # Daily Sales for Last 7 days
    daily_sales = []
    daily_labels = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_revenue = SaleInvoice.objects.filter(
            tenant=request.tenant,
            created_at__date=day
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        daily_sales.append(float(day_revenue))
        daily_labels.append(day.strftime('%a'))
    
    # Top 5 Selling Products
    top_products = SaleItem.objects.filter(
        tenant=request.tenant,
        sale_invoice__created_at__date__gte=thirty_days_ago
    ).values('product__product_name').annotate(
        total_qty=Sum('quantity'),
        total_revenue=Sum('total_amount')
    ).order_by('-total_qty')[:5]
    
    top_product_names = [p['product__product_name'][:15] for p in top_products]
    top_product_qty = [p['total_qty'] for p in top_products]
    
    
    # Total Inventory Value - Make it consistent with Stock Report
    inventory_value = StockBatch.objects.filter(
        tenant=request.tenant,
        current_quantity__gt=0
    ).aggregate(
        total_value=Sum(
            ExpressionWrapper(
                F('current_quantity') * (F('purchase_price') / F('product__conversion_factor')),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            )
        )
    )['total_value'] or 0
    # inventory_value = StockBatch.objects.filter(
    #     tenant=request.tenant
    # ).aggregate(
    #     total_value=Sum(F('current_quantity') * F('purchase_price'), output_field=DecimalField())
    # )['total_value'] or 0
    
    # Customer Growth (Last 7 days)
    new_customers_week = Customer.objects.filter(
        tenant=request.tenant,
        created_at__date__gte=today - timedelta(days=7)
    ).count()
    
    # Total Sales (Last 30 days)
    total_sales_30 = SaleInvoice.objects.filter(
        tenant=request.tenant,
        created_at__date__gte=thirty_days_ago
    ).count()
    
    # Month to Date Revenue
    month_start = today.replace(day=1)
    mtd_revenue = SaleInvoice.objects.filter(
        tenant=request.tenant,
        created_at__date__gte=month_start,
        created_at__date__lte=today
    ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    
    context = {
        'period': period,
        'period_label': period_label,
        'period_revenue': period_revenue,
        'period_transactions': period_transactions,
        'new_customers_period': new_customers_period,
        'today_revenue': today_revenue,
        'total_customers': total_customers,
        'low_stock_count': low_stock_count,
        'prescriptions_count': prescriptions_count,
        'near_expiry_batches': near_expiry_batches,
        'pharmacy_name': request.tenant.pharmacy_name if request.tenant else "Pharmacy App",
        
        # Chart data
        'revenue_trend': json.dumps(revenue_trend),
        'labels_revenue': json.dumps(labels_revenue),
        'daily_sales': json.dumps(daily_sales),
        'daily_labels': json.dumps(daily_labels),
        'payment_labels': json.dumps(payment_labels),
        'payment_data': json.dumps(payment_data),
        'payment_colors': json.dumps(list(payment_colors.values())[:len(payment_labels)]),
        'top_product_names': json.dumps(top_product_names),
        'top_product_qty': json.dumps(top_product_qty),
        
        # Additional metrics
        'inventory_value': inventory_value,
        'new_customers_week': new_customers_week,
        'total_sales_30': total_sales_30,
        'mtd_revenue': mtd_revenue,
    }
    return render(request, "home.html", context)


from django.http import JsonResponse

@login_required
def dashboard_stats_api(request):
    """Lightweight JSON endpoint – called every 30 s by the dashboard for live stats."""
    today = date.today()
    tenant = request.tenant
    if not tenant:
        return JsonResponse({'error': 'No tenant'}, status=403)

    from easypharma.models.stock import StockBatch
    from django.db.models import Sum as DbSum

    today_revenue = SaleInvoice.objects.filter(
        tenant=tenant, created_at__date=today
    ).aggregate(DbSum('total_amount'))['total_amount__sum'] or 0

    today_transactions = SaleInvoice.objects.filter(
        tenant=tenant, created_at__date=today
    ).count()

    total_customers = Customer.objects.filter(tenant=tenant).count()

    low_stock_count = (
        StockBatch.objects
        .filter(tenant=tenant)
        .values('product')
        .annotate(total=DbSum('current_quantity'))
        .filter(total__lt=50)
        .count()
    )

    return JsonResponse({
        'today_revenue':      float(today_revenue),
        'today_transactions': today_transactions,
        'total_customers':    total_customers,
        'low_stock_count':    low_stock_count,
    })

def create_user(request):
    if request.method =='POST':
        username = request.POST.get('username')
        user_type = request.POST.get('user_type')
        password = request.POST.get('password')

        user = User(username=username, user_type=user_type, password=password)
        user.set_password(password)
        user.save()
        messages.success(request, 'User has created successfully!')
        return redirect('/createuser')
    return render(request, 'accounts/createuser.html')

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username")
        password = request.POST.get("password")

        user = authenticate(request, username=username, password=password)

        #Validation check
        if not username:
            messages.error(request, "Username is required.")
            return render(request, "accounts/login.html")

        if not password:
            messages.error(request, "Password is required.")
            return render(request, "accounts/login.html")

        if user is None:
            messages.error(request, "Invalid username or password.")
            return redirect("login")

        if user:
            login(request, user)
            if getattr(user, 'user_type', '') == 'admin':
                return redirect('org_admin_dashboard')
            return redirect("home")
        else:
            return render(request, "accounts/login.html")
    return render(request, "accounts/login.html")

def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        return redirect('login')


# ========== ORGANIZATION ADMIN PANEL ==========

@login_required(login_url='login')
def org_admin_dashboard(request):
    """Organization Admin Dashboard - View all registered pharmacies"""
    # Only system admins can access this
    if request.user.user_type != 'admin':
        messages.error(request, "Access denied. Only administrators can access this panel.")
        return redirect('home')
    
    tenants = Tenant.objects.all().order_by('-created_at')
    context = {
        'tenants': tenants,
        'total_pharmacies': tenants.count(),
    }
    return render(request, 'accounts/org_admin_dashboard.html', context)


@login_required(login_url='login')
@require_http_methods(["GET", "POST"])
def register_pharmacy(request):
    """Pharmacy Registration View - SaaS Organization can register new pharmacies"""
    # Only system admins can register pharmacies
    if request.user.user_type != 'admin':
        messages.error(request, "Access denied. Only administrators can register pharmacies.")
        return redirect('home')
    
    if request.method == 'POST':
        pharmacy_name = request.POST.get('pharmacy_name')
        subdomain = request.POST.get('subdomain')
        address = request.POST.get('address')
        phone = request.POST.get('phone')
        license_number = request.POST.get('license_number')
        gst_number = request.POST.get('gst_number', '')
        owner_username = request.POST.get('owner_username')
        owner_password = request.POST.get('owner_password')
        owner_email = request.POST.get('owner_email', '')
        
        # Validation
        if not all([pharmacy_name, subdomain, address, phone, license_number, owner_username, owner_password]):
            messages.error(request, "All required fields must be filled.")
            return render(request, 'accounts/register_pharmacy.html')
        
        # Check if subdomain already exists
        if Tenant.objects.filter(subdomain=subdomain).exists():
            messages.error(request, f"Subdomain '{subdomain}' already exists. Please choose a different one.")
            return render(request, 'accounts/register_pharmacy.html')
        
        # Check if username already exists
        if User.objects.filter(username=owner_username).exists():
            messages.error(request, "Username already exists. Please choose a different one.")
            return render(request, 'accounts/register_pharmacy.html')
        
        try:
            # Create owner user
            owner = User.objects.create_user(
                username=owner_username,
                user_type='tenant_owner',
                password=owner_password
            )
            
            # Create tenant
            tenant = Tenant(
                name=pharmacy_name,
                subdomain=subdomain,
                pharmacy_name=pharmacy_name,
                address=address,
                phone=phone,
                license_number=license_number,
                gst_number=gst_number,
                owner=owner
            )
            tenant.save()  # This will auto-generate access_key
            
            # Link tenant to owner
            owner.tenant = tenant
            owner.save()
            
            messages.success(
                request,
                f"Pharmacy '{pharmacy_name}' registered successfully! "
                f"Access Key: {tenant.access_key} | Subdomain: {subdomain}"
            )
            return redirect('org_admin_dashboard')
            
        except Exception as e:
            messages.error(request, f"Error registering pharmacy: {str(e)}")
            return render(request, 'accounts/register_pharmacy.html')
    
    return render(request, 'accounts/register_pharmacy.html')


@login_required(login_url='login')
def pharmacy_detail(request, tenant_id):
    """Pharmacy Detail View - View details of a registered pharmacy"""
    if request.user.user_type != 'admin':
        messages.error(request, "Access denied.")
        return redirect('home')
    
    try:
        tenant = Tenant.objects.get(id=tenant_id)
        users_count = User.objects.filter(tenant=tenant).count()
        sales_count = SaleInvoice.objects.filter(tenant=tenant).count()
        total_sales = SaleInvoice.objects.filter(tenant=tenant).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        
        context = {
            'tenant': tenant,
            'users_count': users_count,
            'sales_count': sales_count,
            'total_sales': total_sales,
        }
        return render(request, 'accounts/pharmacy_detail.html', context)
    except Tenant.DoesNotExist:
        messages.error(request, "Pharmacy not found.")
        return redirect('org_admin_dashboard')


@login_required(login_url='login')
def regenerate_access_key(request, tenant_id):
    """Regenerate Access Key for a pharmacy"""
    if request.user.user_type != 'admin':
        messages.error(request, "Access denied.")
        return redirect('home')
    
    try:
        tenant = Tenant.objects.get(id=tenant_id)
        old_key = tenant.access_key
        tenant.access_key = str(uuid.uuid4()).upper()[:12]
        tenant.save()
        
        messages.success(
            request,
            f"Access key regenerated successfully! New Key: {tenant.access_key}"
        )
        return redirect('pharmacy_detail', tenant_id=tenant_id)
    except Tenant.DoesNotExist:
        messages.error(request, "Pharmacy not found.")
        return redirect('org_admin_dashboard')


@login_required(login_url='login')
def deactivate_pharmacy(request, tenant_id):
    """Deactivate a pharmacy"""
    if request.user.user_type != 'admin':
        messages.error(request, "Access denied.")
        return redirect('home')
    
    try:
        tenant = Tenant.objects.get(id=tenant_id)
        tenant.is_active = not tenant.is_active
        tenant.save()
        
        status = "deactivated" if not tenant.is_active else "activated"
        messages.success(request, f"Pharmacy {status} successfully!")
        return redirect('pharmacy_detail', tenant_id=tenant_id)
    except Tenant.DoesNotExist:
        messages.error(request, "Pharmacy not found.")
        return redirect('org_admin_dashboard')

