from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from easypharma.models import User
from django.contrib import messages
from easypharma.models.sales import SaleInvoice, Customer
from easypharma.models.Items import Products
from django.db.models import Sum
from datetime import date

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
