from django.db import models
from tenants.models import SharedModel, TenantAwareModel
class DrugCompany(TenantAwareModel):  # ✅ CHANGED: Inherit from TenantAwareModel
    sht_name = models.CharField(max_length=6, null=True, blank=True)
    company_name = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.company_name

    class Meta:
        verbose_name_plural = "Drug Companies"

class ProductType(TenantAwareModel):  # ✅ CHANGED: Inherit from TenantAwareModel
    name = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class ProductSchedule(TenantAwareModel):  # ✅ CHANGED: Inherit from TenantAwareModel
    schedule_name = models.CharField(max_length=100)

    class Meta:
        unique_together = ('tenant', 'schedule_name')

    def __str__(self):
        return self.schedule_name

class ProductTax(TenantAwareModel):  # ✅ CHANGED: Inherit from TenantAwareModel
    tax_name = models.CharField(max_length=100, null=True, blank=True)
    tax_rate = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.tax_name

    class Meta:
        verbose_name_plural = "Product Taxes"

class ProductContent(TenantAwareModel):  # ✅ CHANGED: Inherit from TenantAwareModel
    content_name = models.CharField(max_length=100)

    def __str__(self):
        return self.content_name

class Products(TenantAwareModel):  # ✅ CHANGED: Inherit from TenantAwareModel
    product_name = models.CharField(max_length=200)
    product_packing = models.CharField(max_length=200, null=True, blank=True)
    product_type = models.ForeignKey(ProductType, on_delete=models.CASCADE, null=True, blank=True)
    product_schedule = models.ForeignKey(ProductSchedule, on_delete=models.CASCADE, null=True, blank=True)
    product_tax = models.ForeignKey(ProductTax, on_delete=models.CASCADE, null=True, blank=True)
    product_hsn_code = models.CharField(max_length=20)
    product_content = models.ForeignKey(ProductContent, on_delete=models.CASCADE, null=True, blank=True)
    compny_name = models.ForeignKey(DrugCompany, on_delete=models.CASCADE, null=True, blank=True)
    conversion_factor = models.PositiveIntegerField(default=1, help_text="Number of units per pack (e.g. 10 tablets per strip)")

    def __str__(self):
        return self.product_name

    class Meta:
        verbose_name_plural = "Products"

# ✅ ADDED: Example of a shared model (same across all tenants)
class SystemSetting(SharedModel):
    setting_name = models.CharField(max_length=100, unique=True)
    setting_value = models.TextField()
    description = models.TextField(blank=True)

    def __str__(self):
        return self.setting_name