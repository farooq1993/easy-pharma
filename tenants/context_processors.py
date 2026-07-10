from easypharma.permissions import get_user_permissions_dict


def tenant_context(request):
    ctx = {
        'current_tenant': getattr(request, 'tenant', None),
        'has_tenant': hasattr(request, 'tenant') and request.tenant is not None,
    }

    # Inject permission flags so sidebar and templates can check them without
    # extra DB queries (the dict is built once per request).
    if hasattr(request, 'user') and request.user.is_authenticated:
        ctx['user_perms'] = get_user_permissions_dict(request.user)
    else:
        ctx['user_perms'] = {}

    return ctx