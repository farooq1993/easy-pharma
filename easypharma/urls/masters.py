from django.urls import path
from easypharma.views.master import (
    ProductTypeListView,DrugScheduleTypeListView,ProductCreate,ProductListView)

urlpatterns = [ 
    path('show-all-product-types/', ProductTypeListView.as_view(), name='show-all-product-types'),
    path('show-all-drug-schedule-types/', DrugScheduleTypeListView.as_view(), name='show-all-drug-schedule-types'),
    path('products/',ProductCreate.as_view(), name='products'),
    path('all-products/', ProductListView.as_view(), name='all-products'),
]
