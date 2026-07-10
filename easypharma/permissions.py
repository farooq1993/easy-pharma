"""
easypharma/permissions.py
─────────────────────────
Central permission helpers for the multi-tenant role-based access system.

Usage in views:
    from easypharma.permissions import module_required

    @login_required
    @module_required('reports')
    def my_report_view(request):
        ...
"""

from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages


# ── Module → permission field mapping ────────────────────────────────────────
MODULE_FIELD_MAP = {
    'sales':        'can_access_sales',
    'purchase':     'can_access_purchase',
    'master':       'can_access_master',
    'reports':      'can_access_reports',
    'gst':          'can_access_gst',
    'accounting':   'can_access_accounting',
    'utility':      'can_access_utility',
    'firm_details': 'can_access_firm_details',
    'users':        'can_manage_users',
}


def has_module_permission(user, module: str) -> bool:
    """
    Return True if the user is allowed to access `module`.

    Rules:
      • admin and tenant_owner → always True
      • Others → check their UserPermission record
      • If no record exists, defaults to False (deny)
    """
    if not user or not user.is_authenticated:
        return False

    # Super-users bypass everything
    if user.user_type in ('admin', 'tenant_owner'):
        return True

    field = MODULE_FIELD_MAP.get(module)
    if not field:
        return False  # Unknown module → deny

    try:
        perm = user.permission_record
        return getattr(perm, field, False)
    except Exception:
        return False


def module_required(module: str, redirect_url: str = 'home'):
    """
    View decorator that enforces module-level access.

    Example:
        @login_required
        @module_required('reports')
        def sales_report_view(request): ...
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('login')
            if not has_module_permission(request.user, module):
                messages.error(
                    request,
                    f"Access denied. You do not have permission to access the "
                    f"'{module.capitalize()}' module. Contact your administrator."
                )
                return redirect(redirect_url)
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def get_or_create_user_permissions(user, tenant):
    """
    Fetch the UserPermission for a user, creating defaults if missing.
    admin / tenant_owner do not need a record; returns None for them.
    """
    if user.user_type in ('admin', 'tenant_owner'):
        return None

    from easypharma.models.accounts import UserPermission

    perm, created = UserPermission.objects.get_or_create(
        user=user,
        defaults={'tenant': tenant}
    )
    if created and perm.tenant != tenant:
        perm.tenant = tenant
        perm.save(update_fields=['tenant'])
    return perm


def get_user_permissions_dict(user) -> dict:
    """
    Return a dict of all permission booleans for template use.
    admin / tenant_owner get all True.
    """
    if not user or not user.is_authenticated:
        return {field: False for field in MODULE_FIELD_MAP.values()}

    if user.user_type in ('admin', 'tenant_owner'):
        return {field: True for field in MODULE_FIELD_MAP.values()}

    try:
        perm = user.permission_record
        return perm.as_dict()
    except Exception:
        return {field: False for field in MODULE_FIELD_MAP.values()}
