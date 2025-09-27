from django.db import models


class DrugCompnay(models.Model):
    sht_name = models.CharField(max_length=6, null=True, blank=True)
    company_name = models.CharField(max_length=100, null=True, blank=True)

    def __str__(self):
        return self.company_name

class ProductType(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

class ProductSchedule(models.Model):
    schedule_name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.schedule_name

class ProductTax(models.Model):
    tax_name = models.CharField(max_length=100, null=True, blank=True)
    tax_rate = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return self.tax_name

class ProductContent(models.Model):
    content_name = models.CharField(max_length=100)

    def __str__(self):
        return self.content_name

class Products(models.Model):
    product_name = models.CharField(max_length=200)
    product_packing = models.CharField(max_length=200, null=True, blank=True)
    product_type = models.ForeignKey(ProductType, on_delete=models.CASCADE, null=True, blank=True)
    product_schedule = models.ForeignKey(ProductSchedule, on_delete=models.CASCADE,null=True, blank=True)
    product_tax = models.ForeignKey(ProductTax, on_delete=models.CASCADE,null=True, blank=True)
    product_hsn_code = models.CharField(max_length=20)
    product_content = models.ForeignKey(ProductContent, on_delete=models.CASCADE,null=True, blank=True)
    compny_name = models.ForeignKey(DrugCompnay, on_delete=models.CASCADE, null=True, blank=True)

    def __str__(self):
        return self.product_name
