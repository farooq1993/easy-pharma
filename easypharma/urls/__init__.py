from easypharma.urls.masters import urlpatterns as master_urls
from easypharma.urls.accounts import urlpatterns as account_urls
from easypharma.urls.sales import urlpatterns as sale_urls
from easypharma.urls.tenants import urlpatterns as tenant_urls
from easypharma.urls.purchase import urlpatterns as purchase_urls
from easypharma.urls.reports import urlpatterns as report_urls

urlpatterns = master_urls + account_urls + sale_urls + tenant_urls + purchase_urls + report_urls