from django.views import View
from django.shortcuts import render, redirect
from django.contrib import messages
from tenants.models import Tenant
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth import get_user_model
import traceback

User = get_user_model()

class RegisterTenantView(LoginRequiredMixin,View):
    template_name = 'tenants/register.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        try:
            pharmacy_name = request.POST.get('pharmacy_name')
            subdomain = request.POST.get('subdomain').lower()
            address = request.POST.get('address')
            phone = request.POST.get('phone')
            license_number = request.POST.get('license_number')
            food_lic = request.POST.get('food_lic')
            
            if Tenant.objects.filter(subdomain=subdomain).exists():
                messages.error(request, "This subdomain is already taken.")
                return render(request, self.template_name)

            # Create the tenant
            tenant = Tenant.objects.create(
                name=pharmacy_name,
                subdomain=subdomain,
                pharmacy_name=pharmacy_name,
                address=address,
                phone=phone,
                license_number=license_number,
                food_lic=food_lic,
                owner=request.user # The currently logged in user becomes the owner
            )

            messages.success(request, f"Pharmacy '{pharmacy_name}' registered successfully! You can now access it at your subdomain.")
            return redirect('home')
        except Exception as e:
            traceback.print_exc()  # Print the traceback to the console for debugging
            messages.error(request, f"An error occurred: {str(e)}")
