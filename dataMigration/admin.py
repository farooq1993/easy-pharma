from .models import MigrationLog
from django.contrib import admin


@admin.register(MigrationLog)
class MigrationLogAdmin(admin.ModelAdmin):
    list_display = ('import_type', 'source_name', 'records_count', 'created_at', 'imported_by', 'status')
    list_filter = ('import_type', 'status', 'created_at')
    search_fields = ('source_name', 'imported_by__username')
    readonly_fields = ('created_at',)