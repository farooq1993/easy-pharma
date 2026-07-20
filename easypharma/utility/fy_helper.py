from datetime import date, datetime
from django.utils import timezone
from easypharma.models.financial_year import FinancialYear


def get_financial_year_dates(dt=None):
    """
    Given a date object or string, returns (start_date, end_date, fy_code).
    Indian Financial Year runs from 01 April of Year N to 31 March of Year N+1.
    For example: 15-May-2025 -> (2025-04-01, 2026-03-31, "25-26")
                 15-Jan-2026 -> (2025-04-01, 2026-03-31, "25-26")
    """
    if dt is None:
        dt = date.today()
    elif isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d').date()
        except ValueError:
            dt = date.today()
    elif isinstance(dt, datetime):
        dt = dt.date()

    year = dt.year
    if dt.month >= 4:
        fy_start_year = year
        fy_end_year = year + 1
    else:
        fy_start_year = year - 1
        fy_end_year = year

    start_date = date(fy_start_year, 4, 1)
    end_date = date(fy_end_year, 3, 31)
    fy_code = f"{str(fy_start_year)[-2:]}-{str(fy_end_year)[-2:]}"

    return start_date, end_date, fy_code


def get_or_create_financial_year(tenant, dt=None):
    """
    Ensures a FinancialYear instance exists for the given date (default today).
    """
    if not tenant:
        return None
    start_date, end_date, fy_code = get_financial_year_dates(dt)
    fy, _ = FinancialYear.objects.get_or_create(
        tenant=tenant,
        fy_code=fy_code,
        defaults={
            'start_date': start_date,
            'end_date': end_date,
            'is_active': True,
            'is_locked': False
        }
    )
    return fy


def is_date_in_locked_fy(tenant, dt):
    """
    Returns True if the specified date falls inside a locked/frozen Financial Year.
    """
    if not tenant or not dt:
        return False
    if isinstance(dt, str):
        try:
            dt = datetime.strptime(dt, '%Y-%m-%d').date()
        except ValueError:
            return False
    elif isinstance(dt, datetime):
        dt = dt.date()

    fy = FinancialYear.objects.filter(
        tenant=tenant,
        start_date__lte=dt,
        end_date__gte=dt,
        is_locked=True
    ).first()

    return bool(fy)


def generate_fy_invoice_number(tenant, invoice_date=None, prefix="INV"):
    """
    Generates a FY-specific invoice number.
    Format: INV-{fy_code}-{seq:04d} (e.g. INV-25-26-0001)
    Every 1st April (or new FY), the sequence automatically resets to 0001!
    """
    from easypharma.models.sales import SaleInvoice
    if not tenant:
        return f"{prefix}-0001"

    start_date, end_date, fy_code = get_financial_year_dates(invoice_date)
    get_or_create_financial_year(tenant, invoice_date)

    fy_prefix = f"{prefix}-{fy_code}-"

    last_inv = SaleInvoice.objects.filter(
        tenant=tenant,
        invoice_number__startswith=fy_prefix
    ).order_by('-id').first()

    if last_inv:
        try:
            last_seq = int(last_inv.invoice_number.split('-')[-1])
            next_seq = last_seq + 1
        except (ValueError, IndexError):
            next_seq = SaleInvoice.objects.filter(
                tenant=tenant,
                created_at__date__gte=start_date,
                created_at__date__lte=end_date
            ).count() + 1
    else:
        next_seq = SaleInvoice.objects.filter(
            tenant=tenant,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        ).count() + 1

    return f"{fy_prefix}{next_seq:04d}"
