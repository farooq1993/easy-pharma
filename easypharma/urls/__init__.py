from easypharma.urls.masters import urlpatterns as master_urls
from easypharma.urls.accounts import urlpatterns as account_urls
from easypharma.urls.sales import urlpatterns as sale_urls
from easypharma.urls.tenants import urlpatterns as tenant_urls
from easypharma.urls.purchase import urlpatterns as purchase_urls
from easypharma.urls.reports import urlpatterns as report_urls
from easypharma.urls.utility import urlpatterns as utility_urls
from easypharma.urls.doctor import urlpatterns as doctor_urls
from easypharma.urls.gst import urlpatterns as gst_urls
from easypharma.urls.accounting import urlpatterns as accounting_urls

urlpatterns = master_urls + account_urls + sale_urls + tenant_urls + purchase_urls + report_urls + utility_urls + doctor_urls + gst_urls + accounting_urls