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
)

urlpatterns = [
    path("", login_view, name="login"),
    path("home", home_view, name="home"),
    path('createuser', create_user, name='create_user'),
    path('logout',logout_view, name='logout'),
    
    # Organization Admin Panel URLs
    path('admin/dashboard', org_admin_dashboard, name='org_admin_dashboard'),
    path('admin/register-pharmacy', register_pharmacy, name='register_pharmacy'),
    path('admin/pharmacy/<int:tenant_id>/', pharmacy_detail, name='pharmacy_detail'),
    path('admin/pharmacy/<int:tenant_id>/regenerate-key', regenerate_access_key, name='regenerate_access_key'),
    path('admin/pharmacy/<int:tenant_id>/deactivate', deactivate_pharmacy, name='deactivate_pharmacy'),
]