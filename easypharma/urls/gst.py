from django.urls import path
from easypharma.views.gst import (
    GSTDashboardView,
    GSTConfigurationView,
    GSTFilingListView,
    GSTFilingDetailView,
    GSTFilingCreateView,
    GSTFilingUpdateView,
    GSTFilingDeleteView,
    GSTReturnDetailView,
    GSTReturnUpdateView,
    GSTReminderListView,
    GSTAPIView,
)

app_name = 'gst'

urlpatterns = [
    # Dashboard and Configuration
    path('gst/', GSTDashboardView.as_view(), name='gst_dashboard'),
    path('gst/config/', GSTConfigurationView.as_view(), name='gst_config'),
    
    # GST Filing CRUD
    path('gst/filings/', GSTFilingListView.as_view(), name='gst_filing_list'),
    path('gst/filings/add/', GSTFilingCreateView.as_view(), name='gst_filing_create'),
    path('gst/filings/<int:pk>/', GSTFilingDetailView.as_view(), name='gst_filing_detail'),
    path('gst/filings/<int:pk>/edit/', GSTFilingUpdateView.as_view(), name='gst_filing_edit'),
    path('gst/filings/<int:pk>/delete/', GSTFilingDeleteView.as_view(), name='gst_filing_delete'),
    
    # GST Return Details
    path('gst/filings/<int:filing_id>/return/', GSTReturnDetailView.as_view(), name='gst_return_detail'),
    path('gst/filings/<int:filing_id>/return/edit/', GSTReturnUpdateView.as_view(), name='gst_return_edit'),
    
    # Reminders
    path('gst/reminders/', GSTReminderListView.as_view(), name='gst_reminder_list'),
    
    # API
    path('gst/api/', GSTAPIView.as_view(), name='gst_api'),
]
