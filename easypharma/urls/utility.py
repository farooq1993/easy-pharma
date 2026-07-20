from django.urls import path
from easypharma.views.utility import (
    UtilityHomeView,
    PrintingSetupView,
    DatabaseBackupView,
    DownloadBackupView,
    DeleteBackupView,
    RestoreBackupView,
    UploadRestoreBackupView,
    BrowseDirectoryView,
    OfflinePageView,
    ServiceWorkerView,
)

from easypharma.views.financial_year import FinancialYearView

urlpatterns = [
    path('settings/', UtilityHomeView.as_view(), name='utility_home'),
    path('financial-years/', FinancialYearView.as_view(), name='financial_year_management'),
    path('printing/', PrintingSetupView.as_view(), name='printing_setup'),
    path('backup/', DatabaseBackupView.as_view(), name='database_backup'),
    path('backup/download/<str:filename>/', DownloadBackupView.as_view(), name='download_backup'),
    path('backup/delete/<str:filename>/', DeleteBackupView.as_view(), name='delete_backup'),
    path('backup/restore/<str:filename>/', RestoreBackupView.as_view(), name='restore_backup'),
    path('backup/upload-restore/', UploadRestoreBackupView.as_view(), name='upload_restore_backup'),
    path('backup/browse-dir/', BrowseDirectoryView.as_view(), name='browse_directory'),
    # PWA routes — no login required
    path('sw.js', ServiceWorkerView.as_view(), name='service_worker'),
    path('offline/', OfflinePageView.as_view(), name='offline_page'),
]
