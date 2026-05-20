from django.urls import path
from . import views

urlpatterns = [
    path('migration/', views.MigrationDashboardView.as_view(), name='migration_dashboard'),
    path('migration/parse/', views.MigrationParseView.as_view(), name='migration_parse'),
    path('migration/import/', views.MigrationImportView.as_view(), name='migration_import'),
    path('migration/status/<int:log_id>/', views.MigrationStatusView.as_view(), name='migration_status'),
    path('migration/rollback/<int:log_id>/', views.MigrationRollbackView.as_view(), name='migration_rollback'),
    path('migration/register-tenant/', views.MigrationRegisterTenantView.as_view(), name='migration_register_tenant'),
]
