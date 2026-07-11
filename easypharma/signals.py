"""
easypharma/signals.py

Signal handlers for:
  1. SaleInvoice / PurchaseInvoice — cache invalidation on save/delete
  2. User — auto-create UserPermission record when a tenant user is saved
  3. Login / Logout — write ActivityLog entries for authentication events
"""
from django.db.models.signals import post_save, post_delete
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
import logging

logger = logging.getLogger('easypharma.signals')


# ── Sale Invoice — daily sale cache invalidate ────────────────────────────────
def _invalidate_on_sale(instance, **kwargs):
    """Har sale save/delete pe daily sale cache clear karo."""
    try:
        from easypharma.views.reports import invalidate_daily_sale_cache
        date_str = str(instance.created_at.date()) if instance.created_at else None
        invalidate_daily_sale_cache(instance.tenant_id, date_str=date_str)
    except Exception as e:
        logger.warning('Cache invalidation failed (sale): %s', e)


# ── Purchase Invoice — stock cache invalidate ─────────────────────────────────
def _invalidate_on_purchase(instance, **kwargs):
    """Har purchase save/delete pe stock report cache clear karo."""
    try:
        from easypharma.views.reports import invalidate_stock_cache
        invalidate_stock_cache(instance.tenant_id)
    except Exception as e:
        logger.warning('Cache invalidation failed (purchase): %s', e)


# ── User — auto-create UserPermission when a tenant user is saved ─────────────
def _auto_create_user_permission(sender, instance, created, **kwargs):
    """
    Whenever a User is saved with a tenant assigned and is NOT admin/tenant_owner,
    ensure a default UserPermission record exists.
    """
    if instance.user_type in ('admin', 'tenant_owner'):
        return  # These roles bypass permission records
    if not instance.tenant_id:
        return  # No tenant yet — skip

    try:
        from easypharma.models.accounts import UserPermission
        UserPermission.objects.get_or_create(
            user=instance,
            defaults={'tenant_id': instance.tenant_id}
        )
    except Exception as e:
        logger.warning('Failed to auto-create UserPermission for %s: %s', instance.username, e)


# ── Login / Logout — activity logging ────────────────────────────────────────
def _log_user_login(sender, request, user, **kwargs):
    """Write an ActivityLog entry when a user logs in."""
    try:
        from easypharma.models.accounts import ActivityLog
        tenant = getattr(request, 'tenant', None)
        ip = ActivityLog._get_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')[:300]
        ActivityLog.objects.create(
            user=user,
            tenant=tenant,
            action_type='LOGIN',
            module='auth',
            description=f'User "{user.username}" logged in.',
            ip_address=ip,
            user_agent=ua,
        )
    except Exception as e:
        logger.warning('Failed to log login for %s: %s', user.username, e)


def _log_user_logout(sender, request, user, **kwargs):
    """Write an ActivityLog entry when a user logs out."""
    try:
        from easypharma.models.accounts import ActivityLog
        tenant = getattr(request, 'tenant', None)
        ip = ActivityLog._get_client_ip(request)
        ua = request.META.get('HTTP_USER_AGENT', '')[:300]
        ActivityLog.objects.create(
            user=user,
            tenant=tenant,
            action_type='LOGOUT',
            module='auth',
            description=f'User "{user.username}" logged out.',
            ip_address=ip,
            user_agent=ua,
        )
    except Exception as e:
        logger.warning('Failed to log logout for %s: %s', user.username, e)


def register_signals():
    """
    apps.py ke ready() se yeh call karo.
    Lazy import — circular import avoid karne ke liye.
    """
    from easypharma.models.sales import SaleInvoice
    from easypharma.models.purchase_invoice import PurchaseInvoice
    from easypharma.models.accounts import User

    post_save.connect(_invalidate_on_sale,     sender=SaleInvoice,     weak=False)
    post_delete.connect(_invalidate_on_sale,   sender=SaleInvoice,     weak=False)
    post_save.connect(_invalidate_on_purchase,   sender=PurchaseInvoice, weak=False)
    post_delete.connect(_invalidate_on_purchase, sender=PurchaseInvoice, weak=False)

    # User permission auto-creation
    post_save.connect(_auto_create_user_permission, sender=User, weak=False)

    # Auth event logging
    user_logged_in.connect(_log_user_login,   weak=False)
    user_logged_out.connect(_log_user_logout, weak=False)