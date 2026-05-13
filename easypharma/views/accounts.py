from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_http_methods
from easypharma.models import User
from django.contrib import messages
from easypharma.models.sales import SaleInvoice, Customer
from easypharma.models.Items import Products
from django.db.models import Sum
from datetime import date
from tenants.models import Tenant
import uuid

def home_view(request):
    today = date.today()
    if not request.tenant:
        messages.warning(request, "No pharmacy linked to your account. Please assign one in Admin.")
    
    # Basic Stats
    today_revenue = SaleInvoice.objects.filter(tenant=request.tenant, created_at__date=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_customers = Customer.objects.filter(tenant=request.tenant).count()
    prescriptions_count = SaleInvoice.objects.filter(tenant=request.tenant, created_at__date=today).count()
    
    # Expiry Alert (within 90 days)
    from datetime import timedelta
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
    
    context = {
        'today_revenue': today_revenue,
        'total_customers': total_customers,
        'low_stock_count': low_stock_count,
        'prescriptions_count': prescriptions_count,
        'near_expiry_batches': near_expiry_batches,
        'pharmacy_name': request.tenant.pharmacy_name if request.tenant else "Pharmacy App"
    }
    return render(request, "home.html", context)

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
        if user:
            login(request, user)
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

