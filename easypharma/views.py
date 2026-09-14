from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib import messages
from django.utils.timezone import now
from .models import User

from .models.sales import SaleInvoice, Customer
from .models.Items import Products
from django.db.models import Sum

@login_required
@ensure_csrf_cookie
def home_view(request):
    today = now().date()   # timezone-aware — daily report se match karega

    today_revenue = (
        SaleInvoice.objects
        .filter(tenant=request.tenant, created_at__date=today)
        .aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    )
    total_customers   = Customer.objects.filter(tenant=request.tenant).count()
    low_stock_count   = Products.objects.filter(tenant=request.tenant).count()
    prescriptions_count = (
        SaleInvoice.objects
        .filter(tenant=request.tenant, created_at__date=today)
        .count()
    )
    from easypharma.models.purchase_invoice import Supplier
    from easypharma.models.accounting import SupplierLedger, SupplierPayment

    # ── Top 5 Suppliers with Credit Balance & Last Payment Details ──
    from django.db.models import Sum, F, DecimalField
    from django.db.models.functions import Coalesce

    # Get top 5 suppliers with positive balance directly via DB aggregation
    top_suppliers_qs = Supplier.objects.filter(tenant=request.tenant).annotate(
        total_credit=Coalesce(Sum('ledger_entries__credit'), 0.0, output_field=DecimalField()),
        total_debit=Coalesce(Sum('ledger_entries__debit'), 0.0, output_field=DecimalField())
    ).annotate(
        balance=F('total_credit') - F('total_debit')
    ).filter(balance__gt=0).order_by('-balance')[:5]

    supplier_balances = []
    
    for s in top_suppliers_qs:
        last_payment = SupplierPayment.objects.filter(
            tenant=request.tenant,
            supplier=s
        ).order_by('-payment_date', '-id').first()
        
        last_payment_date = last_payment.payment_date.strftime('%d/%m/%Y') if last_payment else "--"
        last_payment_amount = float(last_payment.amount) if last_payment else 0.0
        
        supplier_balances.append({
            'name': s.name,
            'balance': float(s.balance),
            'last_payment_date': last_payment_date,
            'last_payment_amount': last_payment_amount
        })
            
    top_suppliers = supplier_balances

    context = {
        'today_revenue':        today_revenue,
        'total_customers':      total_customers,
        'low_stock_count':      low_stock_count,
        'prescriptions_count':  prescriptions_count,
        'today_str':            today.strftime('%Y-%m'),
        'top_suppliers':        top_suppliers,
    }
    return render(request, "home.html", context)

@ensure_csrf_cookie
def login_view(request):
    # Already logged in → redirect
    if request.user.is_authenticated:
        return redirect("home")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect("home")
        else:
            messages.error(request, "Invalid username or password.")
            return render(request, "accounts/login.html")

    return render(request, "accounts/login.html")

def logout_view(request):
    if request.user.is_authenticated:
        logout(request)
        return redirect('login')
    return redirect('login')