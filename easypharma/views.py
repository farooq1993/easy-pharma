from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from .models import User
# Create your views here.


from .models.sales import SaleInvoice, Customer
from .models.Items import Products
from django.db.models import Sum
from datetime import date

def home_view(request):
    today = date.today()
    # Basic Stats
    today_revenue = SaleInvoice.objects.filter(tenant=request.tenant, created_at__date=today).aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_customers = Customer.objects.filter(tenant=request.tenant).count()
    low_stock_count = Products.objects.filter(tenant=request.tenant).count() # Placeholder logic
    prescriptions_count = SaleInvoice.objects.filter(tenant=request.tenant, created_at__date=today).count()
    
    context = {
        'today_revenue': today_revenue,
        'total_customers': total_customers,
        'low_stock_count': low_stock_count,
        'prescriptions_count': prescriptions_count,
    }
    return render(request, "home.html", context)

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
