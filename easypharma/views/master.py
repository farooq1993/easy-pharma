from django.views import View
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
import json

from easypharma.models.Items import (DrugCompnay, ProductContent, 
                                     ProductSchedule,
                                     ProductTax, ProductType, Products)


class ProductTypeListView(View):
    template_name = "masters/show_all_product_types.html"
    http_method_names = ['get', 'post', 'patch', 'delete']

    def dispatch(self, request, *args, **kwargs):
        # Django does not always route PATCH automatically; this ensures it works
        if request.method.lower() == "patch":
            return self.patch(request, *args, **kwargs)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        product_types = ProductType.objects.all()
        product_types = sorted(product_types, key=lambda x: x.name)
        return render(request, self.template_name, {"product_types": product_types})

    def post(self, request, *args, **kwargs):
        name = request.POST.get("name")
        if name:
            ProductType.objects.create(name=name)
            messages.success(request, "Product Type added successfully.")
        else:
            messages.error(request, "Please provide a valid name.")
        return redirect("show-all-product-types")

    def patch(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body.decode("utf-8"))
            product_id = data.get("id")
            name = data.get("name")
            if not product_id or not name:
                return JsonResponse({"error": "Invalid data"}, status=400)
            product_type = get_object_or_404(ProductType, id=product_id)
            product_type.name = name
            product_type.save()
            return JsonResponse({"success": f"Product Type {product_id} updated"})
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)

    def delete(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body.decode("utf-8"))
            product_id = data.get("id")
            if not product_id:
                return JsonResponse({"error": "Invalid data"}, status=400)

            product_type = ProductType.objects.get(id=product_id)
            product_type.delete()
            return JsonResponse({"success": True})
        except ProductType.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)
        

class DrugScheduleTypeListView(View):
    template_name = "masters/drug_schedul.html"
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get(self, request, *args, **kwargs):
        drug_schedules = ProductSchedule.objects.all()
        drug_schedules = sorted(drug_schedules, key=lambda x: x.schedule_name)
        return render(request, self.template_name, {"drug_schedules": drug_schedules})

    def post(self, request, *args, **kwargs):
        schedule_name = request.POST.get("schedule_name")
        if schedule_name:
            # Assuming DrugScheduleType model exists
            ProductSchedule.objects.create(schedule_name=schedule_name)
            messages.success(request, f"Drug Schedule Type '{schedule_name}' added successfully.")
        else:
            messages.error(request, "Please provide a valid name.")
        return redirect("show-all-drug-schedule-types")
    
    def patch(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body.decode("utf-8"))
            schedule_id = data.get("id")
            schedule_name = data.get("schedule_name")
            if not schedule_id or not schedule_name:
                return JsonResponse({"error": "Invalid data"}, status=400)
            
            drug_schedule = get_object_or_404(ProductSchedule, id=schedule_id)
            drug_schedule.schedule_name = schedule_name
            drug_schedule.save()
            
            return JsonResponse({"success": f"Drug Schedule Type {schedule_id} updated"})
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        
    
    def delete(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body.decode("utf-8"))
            schedule_id = data.get("id")
            product_id = data.get("id")
            if not product_id:
                return JsonResponse({"error": "Invalid data"}, status=400)

            product_type =  ProductSchedule.objects.get(id=schedule_id)
            product_type.delete()
            return JsonResponse({"success": True})
        
        except ProductSchedule.DoesNotExist:
            return JsonResponse({"error": "Not found"}, status=404)


class ProductCreate(View):
    template_name = 'masters/product.html'
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get(self, request, *args, **kwargs):
        products = Products.objects.all().select_related(
            'product_type', 'product_schedule', 'product_tax', 'product_content'
        )
        
        
        context = {
            'products': products,
            'product_types': ProductType.objects.all(),
            'product_schedules': ProductSchedule.objects.all(),
            'product_taxes': ProductTax.objects.all(),
            'product_contents': ProductContent.objects.all(),
            'compny_name': DrugCompnay.objects.all(),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        try:
            product_name = request.POST.get("product_name")
            product_packing = request.POST.get("product_packing")
            product_type_id = request.POST.get("product_type")
            product_schedule_id = request.POST.get("product_schedule")
            product_tax_id = request.POST.get("product_tax")
            product_hsn_code = request.POST.get("product_hsn_code")
            product_content_id = request.POST.get("product_content")
            compny_name_id = request.POST.get("compny_name")
            
            # Validate required fields
            if not product_name or not product_hsn_code:
                messages.error(request, "Product Name and HSN Code are required.")
                return redirect("products")
            
            # Create product
            product = Products.objects.create(
                product_name=product_name,
                product_packing=product_packing or None,
                product_type_id=product_type_id or None,
                product_schedule_id=product_schedule_id or None,
                product_tax_id=product_tax_id or None,
                product_hsn_code=product_hsn_code,
                product_content_id=product_content_id or None,
                compny_name = compny_name_id or None
            )
            
            messages.success(request, f"Product '{product_name}' added successfully.")
            
        except Exception as e:
            messages.error(request, f"Error creating product: {str(e)}")
        
        return redirect("products")