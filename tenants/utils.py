from django.db import connections
from .models import Tenant
from easypharma.models import User

def create_pharmacy_tenant(owner_username, pharmacy_data):
    """
    Create a new pharmacy tenant with its own database
    """
    # Get the owner user
    try:
        owner = User.objects.get(username=owner_username)
    except User.DoesNotExist:
        raise ValueError(f"User {owner_username} does not exist")
    
    # Create tenant record
    tenant = Tenant.objects.create(
        name=pharmacy_data['pharmacy_name'],
        subdomain=pharmacy_data['subdomain'],
        pharmacy_name=pharmacy_data['pharmacy_name'],
        address=pharmacy_data.get('address', ''),
        phone=pharmacy_data.get('phone', ''),
        license_number=pharmacy_data.get('license_number', ''),
        owner=owner
    )
    
    # Update owner to be tenant owner
    owner.user_type = 'tenant_owner'
    owner.tenant = tenant
    owner.save()
    
    # Create database (for PostgreSQL/Railway)
    if False:  # Placeholder for database creation logic
        create_tenant_database(tenant)
    
    return tenant

def get_tenant_models():
    """Get all models that are tenant-aware"""
    from django.apps import apps
    from tenants.models import TenantAwareModel
    
    tenant_models = []
    for model in apps.get_models():
        try:
            if issubclass(model, TenantAwareModel) and model != TenantAwareModel:
                tenant_models.append(model)
        except:
            continue
    
    return tenant_models