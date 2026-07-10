from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.utils import timezone

from tenants.models import SharedModel, TenantAwareModel, Tenant

# Shared models (same for all tenants) - inherit from SharedModel
class UserManager(BaseUserManager):
    def create_user(self, username, user_type, password=None, **extra_fields):
        if not username:
            raise ValueError('The Username must be set')
        user = self.model(username=username, user_type=user_type, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, user_type='admin', password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(username, user_type, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin, SharedModel):  
    USER_TYPE = [
        ('admin', 'Admin'),
        ('pharmacist', 'Pharmacist'),
        ('employee', 'Employee'),
        ('tenant_owner', 'Tenant Owner'),  
    ]

    username = models.CharField(max_length=150, unique=True)
    user_type = models.CharField(max_length=20, choices=USER_TYPE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    # ✅ ADDED: Link user to tenant (for tenant-specific users)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['user_type']

    def __str__(self):
        return f"{self.user_type} - {self.username}"

    def is_tenant_owner(self):
        return self.user_type == 'tenant_owner' and self.tenant is not None

    def is_tenant_user(self):
        return self.tenant is not None

    def has_all_permissions(self):
        """admin and tenant_owner always have all rights."""
        return self.user_type in ('admin', 'tenant_owner')


class UserPermission(SharedModel):
    """
    Per-user, per-tenant module-level permission record.
    Only required for pharmacist / employee user types.
    admin and tenant_owner bypass this entirely.
    """
    user = models.OneToOneField(
        'User',
        on_delete=models.CASCADE,
        related_name='permission_record'
    )
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name='user_permissions'
    )

    # ── Module access toggles ─────────────────────────────────────────
    can_access_sales        = models.BooleanField(default=True,  verbose_name='Sales')
    can_access_purchase     = models.BooleanField(default=True,  verbose_name='Purchase')
    can_access_master       = models.BooleanField(default=True,  verbose_name='Master / Inventory')
    can_access_reports      = models.BooleanField(default=False, verbose_name='Reports')
    can_access_gst          = models.BooleanField(default=False, verbose_name='GST Compliance')
    can_access_accounting   = models.BooleanField(default=False, verbose_name='Accounting')
    can_access_utility      = models.BooleanField(default=False, verbose_name='Utility / Settings')
    can_access_firm_details = models.BooleanField(default=False, verbose_name='Firm Details')
    can_manage_users        = models.BooleanField(default=False, verbose_name='User Management')

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'User Permission'
        verbose_name_plural = 'User Permissions'

    def __str__(self):
        return f'Permissions → {self.user.username} @ {self.tenant}'

    def as_dict(self):
        """Return a plain dict for easy template lookups."""
        return {
            'can_access_sales':        self.can_access_sales,
            'can_access_purchase':     self.can_access_purchase,
            'can_access_master':       self.can_access_master,
            'can_access_reports':      self.can_access_reports,
            'can_access_gst':          self.can_access_gst,
            'can_access_accounting':   self.can_access_accounting,
            'can_access_utility':      self.can_access_utility,
            'can_access_firm_details': self.can_access_firm_details,
            'can_manage_users':        self.can_manage_users,
        }


class ActivityLog(SharedModel):
    """
    Tracks user actions across all modules for audit / activity history.
    """
    ACTION_TYPES = [
        ('LOGIN',    'Login'),
        ('LOGOUT',   'Logout'),
        ('CREATE',   'Create'),
        ('UPDATE',   'Update'),
        ('DELETE',   'Delete'),
        ('VIEW',     'View'),
        ('EXPORT',   'Export'),
        ('PERM',     'Permission Change'),
        ('OTHER',    'Other'),
    ]

    MODULE_CHOICES = [
        ('auth',        'Authentication'),
        ('sales',       'Sales'),
        ('purchase',    'Purchase'),
        ('master',      'Master'),
        ('reports',     'Reports'),
        ('gst',         'GST'),
        ('accounting',  'Accounting'),
        ('utility',     'Utility'),
        ('users',       'User Management'),
        ('other',       'Other'),
    ]

    user        = models.ForeignKey(
        'User',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='activity_logs'
    )
    tenant      = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        null=True, blank=True,
        related_name='activity_logs'
    )
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES, default='OTHER')
    module      = models.CharField(max_length=30, choices=MODULE_CHOICES, default='other')
    description = models.TextField()
    ip_address  = models.GenericIPAddressField(null=True, blank=True)
    user_agent  = models.CharField(max_length=300, blank=True)
    timestamp   = models.DateTimeField(default=timezone.now, db_index=True)
    extra_data  = models.JSONField(null=True, blank=True)  # optional structured payload

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'
        indexes = [
            models.Index(fields=['tenant', 'timestamp']),
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['module', 'action_type']),
        ]

    def __str__(self):
        username = self.user.username if self.user else 'Anonymous'
        return f'[{self.timestamp:%Y-%m-%d %H:%M}] {username} → {self.action_type} on {self.module}'

    @classmethod
    def log(cls, request, action_type, module, description, extra_data=None):
        """Convenience class-method to write a log entry from a view."""
        user   = request.user if request.user.is_authenticated else None
        tenant = getattr(request, 'tenant', None)
        ip     = cls._get_client_ip(request)
        ua     = request.META.get('HTTP_USER_AGENT', '')[:300]
        cls.objects.create(
            user=user,
            tenant=tenant,
            action_type=action_type,
            module=module,
            description=description,
            ip_address=ip,
            user_agent=ua,
            extra_data=extra_data,
        )

    @staticmethod
    def _get_client_ip(request):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR')
    




