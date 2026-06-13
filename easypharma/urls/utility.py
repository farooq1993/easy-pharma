from django.urls import path
from easypharma.views.utility import (
    UtilityHomeView, 
    PrintingSetupView,
    DatabaseBackupView,
    DownloadBackupView,
    DeleteBackupView,
    RestoreBackupView,
    UploadRestoreBackupView,
    BrowseDirectoryView
)

urlpatterns = [
    path('settings/', UtilityHomeView.as_view(), name='utility_home'),
    path('printing/', PrintingSetupView.as_view(), name='printing_setup'),
    path('backup/', DatabaseBackupView.as_view(), name='database_backup'),
    path('backup/download/<str:filename>/', DownloadBackupView.as_view(), name='download_backup'),
    path('backup/delete/<str:filename>/', DeleteBackupView.as_view(), name='delete_backup'),
    path('backup/restore/<str:filename>/', RestoreBackupView.as_view(), name='restore_backup'),
    path('backup/upload-restore/', UploadRestoreBackupView.as_view(), name='upload_restore_backup'),
    path('backup/browse-dir/', BrowseDirectoryView.as_view(), name='browse_directory'),
]
