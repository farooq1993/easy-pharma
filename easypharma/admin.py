from django.contrib import admin
from .models import User
from easypharma.models.Items import *
from easypharma.models.purchase_invoice import PurchaseInvoice
# Register your models here.
admin.site.register(User)
admin.site.register(DrugCompnay)
admin.site.register(ProductType)
admin.site.register(ProductSchedule)
admin.site.register(ProductTax)
admin.site.register(ProductContent)
admin.site.register(Products)
admin.site.register(PurchaseInvoice)

