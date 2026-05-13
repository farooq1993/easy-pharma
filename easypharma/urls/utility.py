from django.urls import path
from easypharma.views.utility import UtilityHomeView, PrintingSetupView

urlpatterns = [
    path('settings/', UtilityHomeView.as_view(), name='utility_home'),
    path('printing/', PrintingSetupView.as_view(), name='printing_setup'),
]
