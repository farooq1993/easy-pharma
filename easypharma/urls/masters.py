from django.urls import path
from easypharma.views.master import (
    ProductTypeListView,DrugScheduleTypeListView)

urlpatterns = [ 
    path('show-all-product-types/', ProductTypeListView.as_view(), name='show-all-product-types'),
    path('show-all-drug-schedule-types/', DrugScheduleTypeListView.as_view(), name='show-all-drug-schedule-types'),
]
