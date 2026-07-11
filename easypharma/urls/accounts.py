from django.urls import path
from easypharma.views.accounts import (
    login_view,
    home_view,
    logout_view,
    create_user,
    org_admin_dashboard,
    register_pharmacy,
    pharmacy_detail,
    regenerate_access_key,
    deactivate_pharmacy,
    dashboard_stats_api,
    # User management
    user_management,
    create_tenant_user,
    edit_user_permissions,
    toggle_user_active,
    delete_tenant_user,
    # Activity logs
    activity_logs,
)

urlpatterns = [
    path("", login_view, name="login"),
    path("home", home_view, name="home"),
    path("api/dashboard-stats/", dashboard_stats_api, name="dashboard_stats_api"),
    path('createuser', create_user, name='create_user'),
    path('logout', logout_view, name='logout'),

    # Organization Admin Panel URLs
    path('admin/dashboard', org_admin_dashboard, name='org_admin_dashboard'),
    path('admin/dashboard/', org_admin_dashboard),
    path('adminUser/dashboard', org_admin_dashboard),
    path('adminUser/dashboard/', org_admin_dashboard),
    path('admin/register-pharmacy', register_pharmacy, name='register_pharmacy'),
    path('admin/register-pharmacy/', register_pharmacy),
    path('adminUser/register-pharmacy', register_pharmacy),
    path('adminUser/register-pharmacy/', register_pharmacy),
    path('admin/pharmacy/<int:tenant_id>/', pharmacy_detail, name='pharmacy_detail'),
    path('admin/pharmacy/<int:tenant_id>/regenerate-key', regenerate_access_key, name='regenerate_access_key'),
    path('admin/pharmacy/<int:tenant_id>/deactivate', deactivate_pharmacy, name='deactivate_pharmacy'),

    # ── User Management ────────────────────────────────────────────────────
    path('users/', user_management, name='user_management'),
    path('users/create/', create_tenant_user, name='create_tenant_user'),
    path('users/<int:user_id>/permissions/', edit_user_permissions, name='edit_user_permissions'),
    path('users/<int:user_id>/toggle-active/', toggle_user_active, name='toggle_user_active'),
    path('users/<int:user_id>/delete/', delete_tenant_user, name='delete_tenant_user'),

    # ── Activity Logs ──────────────────────────────────────────────────────
    path('activity-logs/', activity_logs, name='activity_logs'),
]