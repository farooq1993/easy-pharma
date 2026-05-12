from django.http import Http404
from django.shortcuts import redirect
from .models import Tenant

class TenantMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = self.get_tenant(request)
        request.tenant = tenant
        
        # Set tenant context for the current user
        if hasattr(request, 'user') and request.user.is_authenticated:
            self.set_user_tenant_context(request, tenant)
        
        response = self.get_response(request)
        return response

    def get_tenant(self, request):
        # Method 1: Subdomain (production)
        host = request.get_host().split(':')[0]
        host_parts = host.split('.')
        
        if len(host_parts) > 2 and host_parts[0] not in ['www', 'app']:
            subdomain = host_parts[0]
            try:
                return Tenant.objects.get(subdomain=subdomain, is_active=True)
            except Tenant.DoesNotExist:
                pass
        
        # Method 2: URL parameter (development)
        tenant_param = request.GET.get('tenant')
        if tenant_param:
            try:
                return Tenant.objects.get(subdomain=tenant_param, is_active=True)
            except Tenant.DoesNotExist:
                pass
        
        # Method 3: User's default tenant (if user is logged in)
        if hasattr(request, 'user') and request.user.is_authenticated:
            # Check user's direct tenant link
            if hasattr(request.user, 'tenant') and request.user.tenant:
                return request.user.tenant
            
            # Fallback: Query DB directly to bypass any session caching
            from easypharma.models import User
            db_user = User.objects.filter(id=request.user.id).select_related('tenant').first()
            if db_user and db_user.tenant:
                return db_user.tenant
        
        # Method 4: Session (user previously selected tenant)
        tenant_id = request.session.get('tenant_id')
        if tenant_id:
            try:
                return Tenant.objects.get(id=tenant_id, is_active=True)
            except Tenant.DoesNotExist:
                pass
        
        return None

    def set_user_tenant_context(self, request, tenant):
        """Set tenant context for the current user"""
        from easypharma.models import User
        
        if tenant and request.user.tenant != tenant:
            # Update user's tenant context if needed
            if request.user.user_type in ['admin', 'tenant_owner', 'pharmacist', 'employee']:
                request.user.tenant = tenant
                User.objects.filter(pk=request.user.pk).update(tenant=tenant)
        
        # Store tenant in session for future requests
        if tenant:
            request.session['tenant_id'] = tenant.id
        elif 'tenant_id' in request.session:
            del request.session['tenant_id']