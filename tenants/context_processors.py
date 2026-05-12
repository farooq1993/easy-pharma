def tenant_context(request):
    return {
        'current_tenant': getattr(request, 'tenant', None),
        'has_tenant': hasattr(request, 'tenant') and request.tenant is not None,
    }