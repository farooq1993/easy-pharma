from django.conf import settings

class TenantRouter:
    def _is_tenant_model(self, model):
        """Check if model is tenant-aware"""
        # Models that should use tenant-specific database
        tenant_models = [
            'DrugCompany', 'ProductType', 'ProductSchedule', 
            'ProductTax', 'ProductContent', 'Products'
        ]
        
        # Check if model inherits from TenantAwareModel
        try:
            from tenants.models import TenantAwareModel
            if issubclass(model, TenantAwareModel):
                return True
        except:
            pass
        
        return model.__name__ in tenant_models

    def _is_shared_model(self, model):
        """Check if model is shared across all tenants"""
        # Models that should use main database
        shared_models = ['User', 'Tenant', 'SystemSetting', 'Group', 'Permission', 'ContentType', 'Session']
        
        # Check if model inherits from SharedModel (but not TenantAwareModel)
        try:
            from tenants.models import SharedModel, TenantAwareModel
            if issubclass(model, SharedModel) and not issubclass(model, TenantAwareModel):
                return True
        except:
            pass
        
        return model.__name__ in shared_models

    def db_for_read(self, model, **hints):
        if self._is_tenant_model(model):
            # Route to tenant-specific database
            import threading
            for thread in threading.enumerate():
                if hasattr(thread, 'request') and hasattr(thread.request, 'tenant'):
                    tenant = thread.request.tenant
                    if tenant:
                        if settings.ON_RAILWAY:
                            return tenant.database_name
                        else:
                            return 'default'  # SQLite uses same DB with tenant filtering
            return 'default'
        
        elif self._is_shared_model(model):
            return 'default'  # Shared models use main database
        
        return 'default'

    def db_for_write(self, model, **hints):
        return self.db_for_read(model, **hints)

    def allow_relation(self, obj1, obj2, **hints):
        # Allow relations between objects in the same database
        return True

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Allow migrations for all models in their respective databases
        return True