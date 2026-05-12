from django.contrib import admin
from .models import Tenant

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ['pharmacy_name', 'subdomain', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['pharmacy_name', 'subdomain']