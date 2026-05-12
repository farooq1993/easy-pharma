from django.urls import path
from easypharma.views.master import (
    MasterCRUDView, ProductCreate, ProductListView, QuickProductAPI)

urlpatterns = [ 
    # Generic CRUD for masters
    path('type/<str:master_type>/', MasterCRUDView.as_view(), name='master-crud'),
    
    # Specific Product URLs
    path('products/add/', ProductCreate.as_view(), name='products'),
    path('products/all/', ProductListView.as_view(), name='all-products'),
    path('api/products/quick-add/', QuickProductAPI.as_view(), name='quick_product_api'),
    
    # Legacy URL redirects/compatibility
    path('show-all-product-types/', MasterCRUDView.as_view(), {'master_type': 'product-type'}, name='show-all-product-types'),
    path('show-all-drug-schedule-types/', MasterCRUDView.as_view(), {'master_type': 'drug-schedule'}, name='show-all-drug-schedule-types'),
]
