from django.urls import path
from easypharma.views.doctor import (
    DoctorListView, DoctorCreateView, DoctorUpdateView, 
    DoctorDeleteView, DoctorAPIView
)

app_name = 'doctor'

urlpatterns = [
    path('doctor/', DoctorListView.as_view(), name='doctor_list'),
    path('doctor/add/', DoctorCreateView.as_view(), name='doctor_add'),
    path('doctor/<int:pk>/edit/', DoctorUpdateView.as_view(), name='doctor_edit'),
    path('doctor/<int:pk>/delete/', DoctorDeleteView.as_view(), name='doctor_delete'),
    path('doctor/api/', DoctorAPIView.as_view(), name='doctor_api'),
]