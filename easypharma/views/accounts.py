from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods, require_POST
from easypharma.models import User, UserPermission, ActivityLog
from django.contrib import messages
from easypharma.models.sales import SaleInvoice, Customer, SaleItem
from easypharma.models.Items import Products
from django.db.models import Sum, Count, Q, F, DecimalField, ExpressionWrapper
from django.db.models.functions import TruncDate
from datetime import date, timedelta
from tenants.models import Tenant
from easypharma.permissions import module_required, has_module_permission
import uuid
import json


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD / HOME
# ─────────────────────────────────────────────────────────────────────────────

from django.core.cache import cache
from django.db.models.functions import TruncMonth

def get_low_stock_count(tenant):
    from django.db.models import Sum as DbSum
    from easypharma.models.stock import StockBatch
    
    cache_key = f"low_stock_count:{tenant.id}"
    count = cache.get(cache_key)
    if count is None:
        count = (
            StockBatch.objects
            .filter(tenant=tenant)
            .values('product')
            .annotate(total=DbSum('current_quantity'))
            .filter(total__lt=50)
            .count()
        )
        cache.set(cache_key, count, 300) # 5 minutes
    return count



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
    if request.user.is_authenticated:
        if getattr(request.user, 'user_type', '') == 'admin':
            return redirect('org_admin_dashboard')
        return redirect('home')

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
            # Login logging is handled by the user_logged_in signal
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


# ─────────────────────────────────────────────────────────────────────────────
# ORGANIZATION ADMIN PANEL
# ─────────────────────────────────────────────────────────────────────────────

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

            ActivityLog.log(
                request, 'CREATE', 'users',
                f'Admin registered new pharmacy "{pharmacy_name}" (subdomain: {subdomain}), owner: {owner_username}',
            )
            
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


# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT (tenant_owner + admin)
# ─────────────────────────────────────────────────────────────────────────────

def _can_manage_users(user):
    """Return True if the user is allowed to manage other users."""
    if user.user_type in ('admin', 'tenant_owner'):
        return True
    try:
        return user.permission_record.can_manage_users
    except Exception:
        return False


@login_required(login_url='login')
def user_management(request):
    """List all users belonging to the current tenant."""
    if not _can_manage_users(request.user):
        messages.error(request, "Access denied. You cannot manage users.")
        return redirect('home')

    tenant = request.tenant
    if not tenant:
        messages.error(request, "No pharmacy context found.")
        return redirect('home')

    users = User.objects.filter(tenant=tenant).select_related('permission_record').order_by('user_type', 'username')

    context = {
        'users': users,
        'tenant': tenant,
    }
    return render(request, 'accounts/user_management.html', context)


@login_required(login_url='login')
@require_http_methods(["GET", "POST"])
def create_tenant_user(request):
    """Create a new user under the current tenant."""
    if not _can_manage_users(request.user):
        messages.error(request, "Access denied.")
        return redirect('home')

    tenant = request.tenant
    if not tenant:
        messages.error(request, "No pharmacy context found.")
        return redirect('home')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        user_type = request.POST.get('user_type', 'employee')
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        # ── Validation ────────────────────────────────────────────────────
        if not all([username, user_type, password]):
            messages.error(request, "All fields are required.")
            return render(request, 'accounts/create_tenant_user.html', {'tenant': tenant})

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'accounts/create_tenant_user.html', {'tenant': tenant})

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return render(request, 'accounts/create_tenant_user.html', {'tenant': tenant})

        if User.objects.filter(username=username).exists():
            messages.error(request, f"Username '{username}' already exists.")
            return render(request, 'accounts/create_tenant_user.html', {'tenant': tenant})

        # tenant_owner can't create admin users
        allowed_types = ['pharmacist', 'employee']
        if request.user.user_type == 'admin':
            allowed_types.append('tenant_owner')
        if user_type not in allowed_types:
            messages.error(request, "Invalid user type selected.")
            return render(request, 'accounts/create_tenant_user.html', {'tenant': tenant})

        try:
            new_user = User.objects.create_user(
                username=username,
                user_type=user_type,
                password=password,
            )
            new_user.tenant = tenant
            new_user.save()  # signal will auto-create UserPermission

            # Apply initial permissions from the form
            if new_user.user_type not in ('admin', 'tenant_owner'):
                perm, _ = UserPermission.objects.get_or_create(
                    user=new_user,
                    defaults={'tenant': tenant}
                )
                perm.can_access_sales        = request.POST.get('can_access_sales') == 'on'
                perm.can_access_purchase     = request.POST.get('can_access_purchase') == 'on'
                perm.can_access_master       = request.POST.get('can_access_master') == 'on'
                perm.can_access_reports      = request.POST.get('can_access_reports') == 'on'
                perm.can_access_gst          = request.POST.get('can_access_gst') == 'on'
                perm.can_access_accounting   = request.POST.get('can_access_accounting') == 'on'
                perm.can_access_utility      = request.POST.get('can_access_utility') == 'on'
                perm.can_access_firm_details = request.POST.get('can_access_firm_details') == 'on'
                perm.can_manage_users        = request.POST.get('can_manage_users') == 'on'
                perm.save()

            ActivityLog.log(
                request, 'CREATE', 'users',
                f'Created new user "{username}" ({user_type}) under tenant "{tenant}".',
            )
            messages.success(request, f"User '{username}' created successfully!")
            return redirect('user_management')

        except Exception as e:
            messages.error(request, f"Error creating user: {str(e)}")

    return render(request, 'accounts/create_tenant_user.html', {'tenant': tenant})


@login_required(login_url='login')
@require_http_methods(["GET", "POST"])
def edit_user_permissions(request, user_id):
    """Edit module-level permissions for a tenant user."""
    if not _can_manage_users(request.user):
        messages.error(request, "Access denied.")
        return redirect('home')

    tenant = request.tenant
    target_user = get_object_or_404(User, id=user_id, tenant=tenant)

    # Prevent editing admin / tenant_owner via this UI
    if target_user.user_type in ('admin', 'tenant_owner'):
        messages.info(request, f"'{target_user.username}' has all permissions by default and cannot be restricted.")
        return redirect('user_management')

    perm, _ = UserPermission.objects.get_or_create(
        user=target_user,
        defaults={'tenant': tenant}
    )

    if request.method == 'POST':
        perm.can_access_sales        = request.POST.get('can_access_sales') == 'on'
        perm.can_access_purchase     = request.POST.get('can_access_purchase') == 'on'
        perm.can_access_master       = request.POST.get('can_access_master') == 'on'
        perm.can_access_reports      = request.POST.get('can_access_reports') == 'on'
        perm.can_access_gst          = request.POST.get('can_access_gst') == 'on'
        perm.can_access_accounting   = request.POST.get('can_access_accounting') == 'on'
        perm.can_access_utility      = request.POST.get('can_access_utility') == 'on'
        perm.can_access_firm_details = request.POST.get('can_access_firm_details') == 'on'
        perm.can_manage_users        = request.POST.get('can_manage_users') == 'on'
        perm.save()

        ActivityLog.log(
            request, 'PERM', 'users',
            f'Updated permissions for user "{target_user.username}" under tenant "{tenant}".',
            extra_data=perm.as_dict(),
        )
        messages.success(request, f"Permissions updated for '{target_user.username}'.")
        return redirect('user_management')

    context = {
        'target_user': target_user,
        'perm': perm,
        'tenant': tenant,
    }
    return render(request, 'accounts/user_permissions.html', context)


@login_required(login_url='login')
@require_POST
def toggle_user_active(request, user_id):
    """Enable or disable a tenant user."""
    if not _can_manage_users(request.user):
        messages.error(request, "Access denied.")
        return redirect('home')

    tenant = request.tenant
    target_user = get_object_or_404(User, id=user_id, tenant=tenant)

    if target_user == request.user:
        messages.error(request, "You cannot deactivate yourself.")
        return redirect('user_management')

    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=['is_active'])

    status_str = "activated" if target_user.is_active else "deactivated"
    ActivityLog.log(
        request, 'UPDATE', 'users',
        f'User "{target_user.username}" was {status_str} by "{request.user.username}".',
    )
    messages.success(request, f"User '{target_user.username}' has been {status_str}.")
    return redirect('user_management')


@login_required(login_url='login')
@require_POST
def delete_tenant_user(request, user_id):
    """Permanently delete a tenant user."""
    if not _can_manage_users(request.user):
        messages.error(request, "Access denied.")
        return redirect('home')

    tenant = request.tenant
    target_user = get_object_or_404(User, id=user_id, tenant=tenant)

    if target_user == request.user:
        messages.error(request, "You cannot delete yourself.")
        return redirect('user_management')

    if target_user.user_type in ('admin', 'tenant_owner'):
        messages.error(request, "Cannot delete admin or tenant owner accounts.")
        return redirect('user_management')

    username = target_user.username
    target_user.delete()
    ActivityLog.log(
        request, 'DELETE', 'users',
        f'User "{username}" was deleted by "{request.user.username}".',
    )
    messages.success(request, f"User '{username}' has been deleted.")
    return redirect('user_management')


@login_required(login_url='login')
@require_http_methods(["GET", "POST"])
def change_user_password(request, user_id):
    """Change password for a tenant user or self."""
    if not _can_manage_users(request.user) and request.user.id != user_id:
        messages.error(request, "Access denied.")
        return redirect('home')

    tenant = request.tenant
    if request.user.user_type == 'admin':
        target_user = get_object_or_404(User, id=user_id)
    else:
        target_user = get_object_or_404(User, id=user_id, tenant=tenant)

    # Security: A tenant_owner or manager cannot change an admin's password or another tenant_owner's password unless it is their own
    if target_user.user_type in ('admin', 'tenant_owner') and target_user.id != request.user.id:
        if request.user.user_type != 'admin':
            messages.error(request, "Access denied. You cannot change this user's password.")
            return redirect('user_management')

    if request.method == 'POST':
        password = request.POST.get('password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if not password or not confirm_password:
            messages.error(request, "Both password fields are required.")
            return render(request, 'accounts/change_password.html', {'target_user': target_user, 'tenant': tenant})

        if password != confirm_password:
            messages.error(request, "Passwords do not match.")
            return render(request, 'accounts/change_password.html', {'target_user': target_user, 'tenant': tenant})

        if len(password) < 6:
            messages.error(request, "Password must be at least 6 characters.")
            return render(request, 'accounts/change_password.html', {'target_user': target_user, 'tenant': tenant})

        try:
            target_user.set_password(password)
            target_user.save()

            if target_user.id == request.user.id:
                update_session_auth_hash(request, target_user)

            ActivityLog.log(
                request, 'UPDATE', 'users',
                f'Changed password for user "{target_user.username}" (ID: {target_user.id}).',
            )
            messages.success(request, f"Password for '{target_user.username}' updated successfully!")
            return redirect('user_management')

        except Exception as e:
            messages.error(request, f"Error updating password: {str(e)}")

    context = {
        'target_user': target_user,
        'tenant': tenant,
    }
    return render(request, 'accounts/change_password.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY LOGS
# ─────────────────────────────────────────────────────────────────────────────

@login_required(login_url='login')
def activity_logs(request):
    """View activity logs for the current tenant."""
    if not _can_manage_users(request.user):
        messages.error(request, "Access denied. Only admins and tenant owners can view activity logs.")
        return redirect('home')

    tenant = request.tenant
    logs_qs = ActivityLog.objects.filter(tenant=tenant).select_related('user').order_by('-timestamp')

    # Filters
    module_filter = request.GET.get('module', '')
    action_filter = request.GET.get('action', '')
    user_filter   = request.GET.get('user', '')
    days_filter   = request.GET.get('days', '30')

    try:
        days_int = int(days_filter)
    except (ValueError, TypeError):
        days_int = 30

    from django.utils import timezone as tz
    since = tz.now() - timedelta(days=days_int)
    logs_qs = logs_qs.filter(timestamp__gte=since)

    if module_filter:
        logs_qs = logs_qs.filter(module=module_filter)
    if action_filter:
        logs_qs = logs_qs.filter(action_type=action_filter)
    if user_filter:
        logs_qs = logs_qs.filter(user__username__icontains=user_filter)

    # Paginate
    from django.core.paginator import Paginator
    paginator = Paginator(logs_qs, 50)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj':      page_obj,
        'module_filter': module_filter,
        'action_filter': action_filter,
        'user_filter':   user_filter,
        'days_filter':   days_int,
        'module_choices': ActivityLog.MODULE_CHOICES,
        'action_choices': ActivityLog.ACTION_TYPES,
        'tenant': tenant,
    }
    return render(request, 'accounts/activity_logs.html', context)



@login_required
def home_view(request):
    period = request.GET.get('period', 'today')
    today = date.today()
    if not request.tenant:
        messages.warning(request, "No pharmacy linked to your account. Please assign one in Admin.")
    
    tenant_id = request.tenant.id if request.tenant else 0
    cache_key = f"dashboard_dynamic_context_v6:{tenant_id}:{period}"
    
    context = cache.get(cache_key)
    if context is None:
        # Determine date range based on period
        if period == 'month':
            start_date = today.replace(day=1)
            period_label = 'This Month'
            period_days = (today - start_date).days + 1
        elif period == 'year':
            start_date = today.replace(month=1, day=1)
            period_label = 'This Year'
            period_days = (today - start_date).days + 1
        elif period == '7days':
            start_date = today - timedelta(days=6)
            period_label = 'Last 7 Days'
            period_days = 7
        elif period == '30days':
            start_date = today - timedelta(days=29)
            period_label = 'Last 30 Days'
            period_days = 30
        elif period == 'yesterday':
            start_date = today - timedelta(days=1)
            period_label = 'Yesterday'
            period_days = 1
        elif period == 'today':
            start_date = today
            period_label = 'Today'
            period_days = 1
        elif period == 'all':
            start_date = date(2020, 1, 1)
            period_label = 'All Time'
            period_days = 365
        else:
            period = 'today'
            start_date = today
            period_label = 'Today'
            period_days = 1

        # Dynamic Sales Revenue & Invoices for active tenant
        sales_qs = SaleInvoice.objects.filter(tenant=request.tenant) if request.tenant else SaleInvoice.objects.none()
        if period == 'yesterday':
            sales_qs = sales_qs.filter(created_at__date=start_date)
        elif period != 'all':
            sales_qs = sales_qs.filter(created_at__date__gte=start_date, created_at__date__lte=today)

        period_revenue = float(sales_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
        period_transactions = sales_qs.count()

        # Dynamic Purchases for active tenant
        from easypharma.models.purchase_invoice import PurchaseInvoice
        purch_qs = PurchaseInvoice.objects.filter(tenant=request.tenant) if request.tenant else PurchaseInvoice.objects.none()
        if period == 'yesterday':
            purch_qs = purch_qs.filter(purchase_date=start_date)
        elif period != 'all':
            purch_qs = purch_qs.filter(purchase_date__gte=start_date, purchase_date__lte=today)

        period_purchases = float(purch_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0)

        # Dynamic Gross Profit & Margin
        gross_profit = round(period_revenue - period_purchases, 2)
        if period_revenue > 0:
            gross_margin = round((gross_profit / period_revenue) * 100, 1)
        else:
            gross_margin = 0.0

        # Dynamic Customers count for this tenant
        total_customers = Customer.objects.filter(tenant=request.tenant).count() if request.tenant else 0
        new_customers_period = 0
        if request.tenant:
            if period == 'yesterday':
                new_customers_period = Customer.objects.filter(tenant=request.tenant, created_at__date=start_date).count()
            elif period != 'all':
                new_customers_period = Customer.objects.filter(tenant=request.tenant, created_at__date__gte=start_date, created_at__date__lte=today).count()
            else:
                new_customers_period = total_customers

        # Dynamic Sales Growth vs previous period
        sales_growth_str = "0.0%"
        if period != 'all' and request.tenant:
            prev_start = start_date - timedelta(days=period_days)
            prev_end = start_date - timedelta(days=1)
            prev_sales = float(SaleInvoice.objects.filter(
                tenant=request.tenant,
                created_at__date__gte=prev_start,
                created_at__date__lte=prev_end
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
            if prev_sales > 0:
                growth_val = round(((period_revenue - prev_sales) / prev_sales) * 100, 1)
                sales_growth_str = f"+{growth_val}%" if growth_val >= 0 else f"{growth_val}%"
            elif period_revenue > 0:
                sales_growth_str = "+100%"
            else:
                sales_growth_str = "0.0%"
        elif period == 'all':
            sales_growth_str = "All-Time"

        # Dynamic Purchase Growth
        purchase_growth_str = "0.0%"
        if period != 'all' and request.tenant:
            prev_start = start_date - timedelta(days=period_days)
            prev_end = start_date - timedelta(days=1)
            prev_purch = float(PurchaseInvoice.objects.filter(
                tenant=request.tenant,
                purchase_date__gte=prev_start,
                purchase_date__lte=prev_end
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0)
            if prev_purch > 0:
                pgrowth_val = round(((period_purchases - prev_purch) / prev_purch) * 100, 1)
                purchase_growth_str = f"+{pgrowth_val}%" if pgrowth_val >= 0 else f"{pgrowth_val}%"
            elif period_purchases > 0:
                purchase_growth_str = "+100%"
            else:
                purchase_growth_str = "0.0%"
        elif period == 'all':
            purchase_growth_str = "All-Time"

        customer_growth_str = f"+{new_customers_period}"

        # Dynamic Stock Status
        from easypharma.models.stock import StockBatch
        active_batches = StockBatch.objects.filter(tenant=request.tenant, current_quantity__gt=0) if request.tenant else StockBatch.objects.none()
        total_active_batches = active_batches.count()

        near_expiry_count = active_batches.filter(expiry_date__lte=today + timedelta(days=90)).count()
        low_stock_count = active_batches.filter(current_quantity__lte=10).count()
        all_products_count = Products.objects.filter(tenant=request.tenant).count() if request.tenant else 0
        products_with_stock = active_batches.values_list('product_id', flat=True).distinct().count()
        out_of_stock_count = max(0, all_products_count - products_with_stock)

        in_stock_count = max(0, total_active_batches - low_stock_count)

        total_stock_items = total_active_batches if total_active_batches > 0 else all_products_count
        denom = max(1, total_stock_items)

        in_stock_pct = round((in_stock_count / denom) * 100, 1)
        low_stock_pct = round((low_stock_count / denom) * 100, 1)
        out_of_stock_pct = round((out_of_stock_count / max(1, all_products_count)) * 100, 1) if all_products_count else 0.0
        near_expiry_pct = round((near_expiry_count / denom) * 100, 1)

        # Dynamic Near Expiry Batches List
        near_expiry_qs = StockBatch.objects.filter(
            tenant=request.tenant,
            expiry_date__lte=today + timedelta(days=90),
            current_quantity__gt=0
        ).select_related('product').order_by('expiry_date')[:50] if request.tenant else []

        near_expiry_batches = []
        near_expiry_total_val = 0.0
        exp_30_count = 0
        exp_60_count = 0
        exp_90_count = 0

        expired_count = 0
        for b in near_expiry_qs:
            days = (b.expiry_date - today).days if b.expiry_date else 0
            is_expired = days <= 0
            if is_expired:
                expired_count += 1
            val = float(b.current_quantity) * float(b.mrp or b.sale_price or b.purchase_price or 0)
            near_expiry_total_val += val
            if days <= 30:
                exp_30_count += 1
                cat = '<=30'
            elif days <= 60:
                exp_60_count += 1
                cat = '31-60'
            else:
                exp_90_count += 1
                cat = '61-90'

            near_expiry_batches.append({
                'id': b.id,
                'product_name': b.product.product_name if b.product else 'Unknown Product',
                'batch_number': b.batch_number or 'N/A',
                'expiry_date': b.expiry_date.strftime('%d %b %Y') if b.expiry_date else 'N/A',
                'days_left': days,
                'is_expired': is_expired,
                'stock': b.current_quantity,
                'mrp': float(b.mrp or b.sale_price or 0),
                'total_value': round(val, 2),
                'category': cat,
            })
        near_expiry_total_val = round(near_expiry_total_val, 2)

        # Dynamic Sales & Purchase Trend Chart (6 buckets)
        step = 5
        if period in ['today', 'yesterday', '7days']:
            step = 1
        elif period in ['year', 'all']:
            step = 30

        trend_labels = []
        trend_sales = []
        trend_purchase = []

        for i in range(5, -1, -1):
            b_end = today - timedelta(days=i * step)
            b_start = b_end - timedelta(days=step - 1)
            
            s_sum = float(SaleInvoice.objects.filter(
                tenant=request.tenant,
                created_at__date__gte=b_start,
                created_at__date__lte=b_end
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0) if request.tenant else 0.0
            
            p_sum = float(PurchaseInvoice.objects.filter(
                tenant=request.tenant,
                purchase_date__gte=b_start,
                purchase_date__lte=b_end
            ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0) if request.tenant else 0.0
            
            trend_labels.append(b_end.strftime('%d %b'))
            trend_sales.append(round(s_sum, 2))
            trend_purchase.append(round(p_sum, 2))

        # Dynamic Top Selling Products
        top_selling_qs = SaleItem.objects.filter(tenant=request.tenant) if request.tenant else SaleItem.objects.none()
        if period != 'all':
            top_selling_qs = top_selling_qs.filter(
                sale_invoice__created_at__date__gte=start_date,
                sale_invoice__created_at__date__lte=today
            )
        
        top_products_data = list(top_selling_qs.values('product__product_name').annotate(
            total_qty=Sum('quantity'),
            total_revenue=Sum('total_amount')
        ).order_by('-total_qty')[:5])

        # If no sales in current period, get top selling overall for tenant
        if not top_products_data and request.tenant:
            top_products_data = list(SaleItem.objects.filter(tenant=request.tenant).values('product__product_name').annotate(
                total_qty=Sum('quantity'),
                total_revenue=Sum('total_amount')
            ).order_by('-total_qty')[:5])

        top_products = []
        for tp in top_products_data:
            top_products.append({
                'product_name': tp['product__product_name'] or 'Medicine',
                'total_qty': tp['total_qty'] or 0,
                'total_revenue': float(tp['total_revenue'] or 0)
            })

        # Dynamic AI Purchase Suggestions based on REAL low-stock batches
        low_stock_qs = StockBatch.objects.filter(
            tenant=request.tenant,
            current_quantity__gt=0,
            current_quantity__lte=25
        ).select_related('product').order_by('current_quantity')[:4] if request.tenant else []

        from easypharma.models.purchase_invoice import PurchaseItem

        icons = ['bi-capsule', 'bi-capsule-pill', 'bi-prescription2', 'bi-droplet-half']
        bg_classes = ['ai-box-blue', 'ai-box-orange', 'ai-box-purple', 'ai-box-blue']

        ai_purchase_suggestions = []
        for idx, b in enumerate(low_stock_qs):
            suggested_buy = max(50, 100 - b.current_quantity)
            supplier_items = PurchaseItem.objects.filter(
                tenant=request.tenant,
                product_id=b.product_id,
                purchase_invoice__tenant=request.tenant,
                purchase_invoice__supplier__isnull=False,
                purchase_invoice__supplier__tenant=request.tenant,
            ).select_related(
                'purchase_invoice__supplier'
            ).order_by('-purchase_invoice__created_at', '-id')

            seen_supplier_ids = set()
            best_supplier_name = None
            best_unit_profit = None
            for purchase_item in supplier_items:
                supplier = purchase_item.purchase_invoice.supplier
                if supplier.id in seen_supplier_ids:
                    continue
                seen_supplier_ids.add(supplier.id)

                unit_profit = purchase_item.sale_price - purchase_item.purchase_price
                if best_unit_profit is None or unit_profit > best_unit_profit:
                    best_supplier_name = supplier.name
                    best_unit_profit = unit_profit

            ai_purchase_suggestions.append({
                'name': b.product.product_name if b.product else 'Medicine',
                'stock': b.current_quantity,
                'buy_qty': suggested_buy,
                'supplier_name': best_supplier_name or 'Not available',
                'unit_profit': float(best_unit_profit) if best_unit_profit is not None else None,
                'bg_class': bg_classes[idx % len(bg_classes)],
                'icon': icons[idx % len(icons)],
            })

        # Dynamic Compliance status
        has_h1 = Products.objects.filter(tenant=request.tenant, product_schedule__schedule_name__icontains='H1').exists() if request.tenant else False
        has_h = Products.objects.filter(tenant=request.tenant, product_schedule__schedule_name__icontains='H').exclude(product_schedule__schedule_name__icontains='H1').exists() if request.tenant else False
        has_narcotic = Products.objects.filter(tenant=request.tenant, product_schedule__schedule_name__icontains='Narcotic').exists() if request.tenant else False

        # Dynamic Business Health Score
        score = 50
        if period_revenue > 0:
            score += 20
        if in_stock_pct >= 70:
            score += 15
        elif in_stock_pct >= 40:
            score += 10
        if near_expiry_count <= 20:
            score += 10
        if total_active_batches > 0:
            score += 5
        business_score = min(98, max(45, score))

        # Dynamic Tenant details - 100% dynamic, NO static hardcoding!
        pharmacy_name = ""
        if request.tenant:
            pharmacy_name = request.tenant.pharmacy_name or request.tenant.name or ""
        if not pharmacy_name:
            pharmacy_name = "Easy Pharma"

        pharmacy_city = getattr(request.tenant, 'city', '') or ""
        pharmacy_state = getattr(request.tenant, 'state', '') or ""
        pharmacy_address = getattr(request.tenant, 'address', '') or ""

        user_full_name = request.user.username.title() if hasattr(request.user, 'username') and request.user.username else "User"
        user_initials = request.user.username[:2].upper() if hasattr(request.user, 'username') and len(request.user.username) >= 2 else "U"
        user_role = request.user.get_user_type_display() if hasattr(request.user, 'get_user_type_display') else getattr(request.user, 'user_type', 'Admin').title()

        context = {
            'period': period,
            'period_label': period_label,
            'period_revenue': period_revenue,
            'period_purchases': period_purchases,
            'gross_profit': gross_profit,
            'gross_margin': gross_margin,
            'total_customers': total_customers,
            'sales_growth_str': sales_growth_str,
            'purchase_growth_str': purchase_growth_str,
            'customer_growth_str': customer_growth_str,
            'today': today,

            # Stock breakdown
            'total_stock_items': total_stock_items,
            'in_stock_count': in_stock_count,
            'in_stock_pct': in_stock_pct,
            'low_stock_count': low_stock_count,
            'low_stock_pct': low_stock_pct,
            'out_of_stock_count': out_of_stock_count,
            'out_of_stock_pct': out_of_stock_pct,
            'near_expiry_count': near_expiry_count,
            'near_expiry_pct': near_expiry_pct,

            # Charts JSON
            'trend_labels_json': json.dumps(trend_labels),
            'trend_sales_json': json.dumps(trend_sales),
            'trend_purchase_json': json.dumps(trend_purchase),

            # Near Expiry Table
            'near_expiry_batches': near_expiry_batches,
            'near_expiry_total_val': near_expiry_total_val,
            'exp_30_count': exp_30_count,
            'exp_60_count': exp_60_count,
            'exp_90_count': exp_90_count,
            'expired_count': expired_count,

            # Bottom sections
            'top_products': top_products,
            'ai_purchase_suggestions': ai_purchase_suggestions,

            # Compliance
            'has_h1': has_h1,
            'has_h': has_h,
            'has_narcotic': has_narcotic,

            # Business Score
            'business_score': business_score,

            # User & Tenant
            'pharmacy_name': pharmacy_name,
            'pharmacy_city': pharmacy_city,
            'pharmacy_state': pharmacy_state,
            'pharmacy_address': pharmacy_address,
            'user_full_name': user_full_name,
            'user_initials': user_initials,
            'user_role': user_role,
        }
        cache.set(cache_key, context, 60)
        
    return render(request, "home.html", context)


@login_required
def dashboard_stats_api(request):
    """Lightweight JSON endpoint – called every 30 s by the dashboard for live stats."""
    period = request.GET.get('period', 'today')
    today = date.today()
    tenant = request.tenant
    if not tenant:
        return JsonResponse({'error': 'No tenant'}, status=403)

    if period == 'month':
        start_date = today.replace(day=1)
    elif period == 'year':
        start_date = today.replace(month=1, day=1)
    else:
        start_date = today

    from django.db.models import Sum as DbSum

    period_revenue = SaleInvoice.objects.filter(
        tenant=tenant, 
        created_at__date__gte=start_date,
        created_at__date__lte=today
    ).aggregate(DbSum('total_amount'))['total_amount__sum'] or 0

    period_transactions = SaleInvoice.objects.filter(
        tenant=tenant, 
        created_at__date__gte=start_date,
        created_at__date__lte=today
    ).count()

    total_customers = Customer.objects.filter(tenant=tenant).count()

    # Cached low stock count
    low_stock_count = get_low_stock_count(tenant)

    return JsonResponse({
        'period_revenue':      float(period_revenue),
        'period_transactions': period_transactions,
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

