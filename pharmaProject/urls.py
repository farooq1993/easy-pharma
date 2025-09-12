from django.contrib import admin
from django.urls import path,include


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('easypharma.urls')),
    path('master/', include('easypharma.urls.masters')),
]

