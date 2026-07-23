from django.db import models
from tenants.models import Tenant


class PrintSetup(models.Model):
    PAPER_SIZE_CHOICES = [
        ('A4', 'A4 (210mm × 297mm)'),
        ('80mm', '80mm Thermal'),
        ('58mm', '58mm Thermal'),
        ('8x4', 'Epson LX310 Standard (8" × 4" Dot Matrix)'),
        ('4x6',  'Epson LX310 — 4" × 6" Standard Bill')
    ]

    tenant = models.OneToOneField(Tenant, on_delete=models.CASCADE, related_name='print_setup')

    # Logo (stored as base64 text to avoid media file complexity)
    logo_base64 = models.TextField(null=True, blank=True, help_text="Logo image stored as base64 string")

    # Paper settings
    paper_size = models.CharField(max_length=10, choices=PAPER_SIZE_CHOICES, default='A4')

    # Signature settings
    show_customer_signature = models.BooleanField(default=False)
    show_pharmacist_signature = models.BooleanField(default=True)

    # Content settings
    custom_header = models.TextField(null=True, blank=True, help_text="Extra text below pharmacy name")
    custom_footer = models.TextField(null=True, blank=True, help_text="Footer message on invoice")
    show_logo = models.BooleanField(default=True)
    show_gst_details = models.BooleanField(default=True)
    show_dl_details = models.BooleanField(default=True)
    print_single_copy = models.BooleanField(default=False, help_text="If true, prints a single copy instead of original + duplicate (For carbon paper)")

    # Margins (in mm)
    margin_top = models.IntegerField(default=10)
    margin_sides = models.IntegerField(default=10)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"PrintSetup for {self.tenant.pharmacy_name}"
