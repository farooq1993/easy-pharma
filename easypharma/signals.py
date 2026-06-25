"""
easypharma/signals.py

Yeh file SaleInvoice aur PurchaseInvoice save/delete hone pe
automatically cache invalidate karti hai.

Setup (ek baar karna hai):
  easypharma/apps.py mein ready() mein import karo (niche example hai).
"""
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


# ── Sale Invoice — daily sale cache invalidate ────────────────────────────────
def _invalidate_on_sale(instance, **kwargs):
    """Har sale save/delete pe daily sale cache clear karo."""
    try:
        from easypharma.reports import invalidate_daily_sale_cache
        date_str = str(instance.created_at.date()) if instance.created_at else None
        invalidate_daily_sale_cache(instance.tenant_id, date_str=date_str)
    except Exception as e:
        import logging
        logging.getLogger('easypharma.signals').warning(
            'Cache invalidation failed (sale): %s', e
        )


# ── Purchase Invoice — stock cache invalidate ─────────────────────────────────
def _invalidate_on_purchase(instance, **kwargs):
    """Har purchase save/delete pe stock report cache clear karo."""
    try:
        from easypharma.reports import invalidate_stock_cache
        invalidate_stock_cache(instance.tenant_id)
    except Exception as e:
        import logging
        logging.getLogger('easypharma.signals').warning(
            'Cache invalidation failed (purchase): %s', e
        )


def register_signals():
    """
    apps.py ke ready() se yeh call karo.
    Lazy import — circular import avoid karne ke liye.
    """
    from easypharma.models.sales import SaleInvoice
    from easypharma.models.purchase_invoice import PurchaseInvoice

    post_save.connect(_invalidate_on_sale,     sender=SaleInvoice,     weak=False)
    post_delete.connect(_invalidate_on_sale,   sender=SaleInvoice,     weak=False)
    post_save.connect(_invalidate_on_purchase,   sender=PurchaseInvoice, weak=False)
    post_delete.connect(_invalidate_on_purchase, sender=PurchaseInvoice, weak=False)