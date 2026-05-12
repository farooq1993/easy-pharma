from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager

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
    


# class UserManager(BaseUserManager):
#     def create_user(self, username, user_type, password=None, **extra_fields):
#         if not username:
#             raise ValueError('The Username must be set')
#         user = self.model(username=username, user_type=user_type, **extra_fields)
#         user.set_password(password)
#         user.save(using=self._db)
#         return user

#     def create_superuser(self, username, user_type='admin', password=None, **extra_fields):
#         extra_fields.setdefault('is_staff', True)
#         extra_fields.setdefault('is_superuser', True)
#         return self.create_user(username, user_type, password, **extra_fields)

# class User(AbstractBaseUser, PermissionsMixin):
#     USER_TYPE = [
#         ('admin', 'Admin'),
#         ('pharmacist', 'Pharmacist'),
#         ('employee', 'Employee'),
#     ]

#     username = models.CharField(max_length=150, unique=True)
#     user_type = models.CharField(max_length=20, choices=USER_TYPE)
#     created_at = models.DateTimeField(auto_now_add=True)
#     updated_at = models.DateTimeField(auto_now=True)
#     is_active = models.BooleanField(default=True)
#     is_staff = models.BooleanField(default=False)

#     objects = UserManager()

#     USERNAME_FIELD = 'username'
#     REQUIRED_FIELDS = ['user_type']

#     def __str__(self):
#         return f"{self.user_type} - {self.username}"