from easypharma.models.doctor import DoctorModel
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
import json


class DoctorListView(LoginRequiredMixin, ListView):
    model = DoctorModel
    template_name = 'doctor/doctor_list.html'
    context_object_name = 'doctors'
    login_url = 'login/'

    def get_queryset(self):
        return DoctorModel.objects.filter(tenant=self.request.tenant).order_by('-created_at')


class DoctorCreateView(LoginRequiredMixin, CreateView):
    model = DoctorModel
    template_name = 'doctor/doctor_form.html'
    fields = ['name', 'phone', 'email', 'specialization', 'is_default']
    success_url = reverse_lazy('doctor_list')
    login_url = 'login/'

    def form_valid(self, form):
        form.instance.tenant = self.request.tenant
        messages.success(self.request, 'Doctor added successfully.')
        return super().form_valid(form)


class DoctorUpdateView(LoginRequiredMixin, UpdateView):
    model = DoctorModel
    template_name = 'doctor/doctor_form.html'
    fields = ['name', 'phone', 'email', 'specialization', 'is_default']
    success_url = reverse_lazy('doctor_list')
    login_url = 'login/'

    def get_queryset(self):
        return DoctorModel.objects.filter(tenant=self.request.tenant)

    def form_valid(self, form):
        messages.success(self.request, 'Doctor updated successfully.')
        return super().form_valid(form)


class DoctorDeleteView(LoginRequiredMixin, DeleteView):
    model = DoctorModel
    success_url = reverse_lazy('doctor_list')
    login_url = 'login/'

    def get_queryset(self):
        return DoctorModel.objects.filter(tenant=self.request.tenant)

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Doctor deleted successfully.')
        return super().delete(request, *args, **kwargs)


# API View for AJAX operations
@method_decorator(login_required(login_url='login/'), name='dispatch')
class DoctorAPIView(ListView):
    def get(self, request, *args, **kwargs):
        doctors = DoctorModel.objects.filter(tenant=request.tenant).values('id', 'name', 'phone', 'email', 'specialization')
        return JsonResponse(list(doctors), safe=False)

    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            doctor = DoctorModel.objects.create(
                tenant=request.tenant,
                name=data['name'],
                phone=data.get('phone'),
                email=data.get('email'),
                specialization=data.get('specialization'),
                is_default=data.get('is_default', False)
            )
            return JsonResponse({'success': True, 'id': doctor.id})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    def patch(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            doctor = get_object_or_404(DoctorModel, id=data['id'], tenant=request.tenant)
            for field in ['name', 'phone', 'email', 'specialization', 'is_default']:
                if field in data:
                    setattr(doctor, field, data[field])
            doctor.save()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    def delete(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            doctor = get_object_or_404(DoctorModel, id=data['id'], tenant=request.tenant)
            doctor.delete()
            return JsonResponse({'success': True})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})


