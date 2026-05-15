"""
Management command: seed_products
Usage: python manage.py seed_products --tenant <subdomain>

Seeds realistic Indian pharmacy product data with:
  - Drug companies
  - Product schedules
  - Drug contents (compositions)
  - Products linked to all the above
"""
from django.core.management.base import BaseCommand, CommandError
from tenants.models import Tenant
from easypharma.models.Items import (
    DrugCompany, ProductSchedule, ProductContent, ProductType, ProductTax, Products
)


COMPANIES = [
    ("SUN", "Sun Pharmaceutical Industries Ltd"),
    ("CIP", "Cipla Ltd"),
    ("DRL", "Dr. Reddy's Laboratories Ltd"),
    ("ZYD", "Zydus Cadila"),
    ("ALK", "Alkem Laboratories Ltd"),
    ("AUR", "Aurobindo Pharma Ltd"),
    ("LUP", "Lupin Ltd"),
    ("GLE", "Glenmark Pharmaceuticals Ltd"),
    ("ABT", "Abbott India Ltd"),
    ("IPC", "IPCA Laboratories Ltd"),
    ("TOR", "Torrent Pharmaceuticals Ltd"),
    ("MAN", "Mankind Pharma Ltd"),
    ("MIC", "Micro Labs Ltd"),
    ("WIN", "Wockhardt Ltd"),
    ("PFZ", "Pfizer Ltd"),
]

SCHEDULES = [
    "Schedule H",
    "Schedule H1",
    "Schedule G",
    "Schedule X",
    "OTC",
    "Prescription Only",
]

TYPES = [
    "Tablet", "Capsule", "Syrup", "Injection", "Cream",
    "Ointment", "Drops", "Inhaler", "Suspension", "Gel",
]

# (content_name, [(product_name, packing, company_sht, schedule, type, hsn)])
PRODUCTS_DATA = [
    # ── Paracetamol / PCM ──────────────────────────────────────────────
    ("Paracetamol 500mg", [
        ("Dolo 650",        "10x10",  "MIC", "OTC",          "Tablet",  "3004"),
        ("Calpol 500",      "10x10",  "GLE", "OTC",          "Tablet",  "3004"),
        ("Crocin 500",      "1x15",   "ABT", "OTC",          "Tablet",  "3004"),
        ("Pacimol 500",     "10x10",  "IPC", "OTC",          "Tablet",  "3004"),
        ("Febrex 650",      "10x10",  "CIP", "OTC",          "Tablet",  "3004"),
        ("P-500",           "10x10",  "ZYD", "OTC",          "Tablet",  "3004"),
    ]),
    ("Paracetamol 125mg/5ml Syrup", [
        ("Calpol Syrup 60ml","60ml",   "ABT", "OTC",         "Syrup",   "3004"),
        ("Dolo Syrup",       "60ml",   "MIC", "OTC",         "Syrup",   "3004"),
    ]),
    # ── Amoxicillin ────────────────────────────────────────────────────
    ("Amoxicillin 500mg", [
        ("Mox 500",         "1x10",   "AUR", "Schedule H",   "Capsule", "3004"),
        ("Novamox 500",     "1x10",   "CIP", "Schedule H",   "Capsule", "3004"),
        ("Amoxil 500",      "1x10",   "PFZ", "Schedule H",   "Capsule", "3004"),
        ("Amoxyclav 625",   "1x10",   "SUN", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Azithromycin ───────────────────────────────────────────────────
    ("Azithromycin 500mg", [
        ("Azithral 500",    "1x3",    "ABT", "Schedule H",   "Tablet",  "3004"),
        ("Zithromax 500",   "1x3",    "PFZ", "Schedule H",   "Tablet",  "3004"),
        ("Azee 500",        "1x3",    "CIP", "Schedule H",   "Tablet",  "3004"),
        ("Atm 500",         "1x3",    "LUP", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Metformin ──────────────────────────────────────────────────────
    ("Metformin 500mg", [
        ("Glycomet 500",    "10x10",  "ABT", "Schedule H",   "Tablet",  "3004"),
        ("Glucophage 500",  "10x10",  "DRL", "Schedule H",   "Tablet",  "3004"),
        ("Obimet 500",      "10x10",  "GLE", "Schedule H",   "Tablet",  "3004"),
        ("Metlong 500",     "10x10",  "SUN", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Atorvastatin ───────────────────────────────────────────────────
    ("Atorvastatin 10mg", [
        ("Lipitor 10",      "10x10",  "PFZ", "Schedule H",   "Tablet",  "3004"),
        ("Atorva 10",       "10x10",  "ZYD", "Schedule H",   "Tablet",  "3004"),
        ("Tonact 10",       "10x10",  "LUP", "Schedule H",   "Tablet",  "3004"),
        ("Storvas 10",      "10x10",  "SUN", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Pantoprazole ───────────────────────────────────────────────────
    ("Pantoprazole 40mg", [
        ("Pan 40",          "1x10",   "ALK", "Schedule H",   "Tablet",  "3004"),
        ("Pantocid 40",     "1x10",   "SUN", "Schedule H",   "Tablet",  "3004"),
        ("Nexpro 40",       "1x10",   "TOR", "Schedule H",   "Tablet",  "3004"),
        ("Pantop 40",       "1x10",   "AUR", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Cetirizine ─────────────────────────────────────────────────────
    ("Cetirizine 10mg", [
        ("Zyrtec 10",       "1x10",   "PFZ", "Schedule H",   "Tablet",  "3004"),
        ("Cetzine 10",      "1x15",   "CIP", "Schedule H",   "Tablet",  "3004"),
        ("CTZ 10",          "1x15",   "DRL", "Schedule H",   "Tablet",  "3004"),
        ("Alerid 10",       "1x10",   "ZYD", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Montelukast ────────────────────────────────────────────────────
    ("Montelukast 10mg", [
        ("Montair 10",      "1x10",   "CIP", "Schedule H",   "Tablet",  "3004"),
        ("Montek LC",       "1x10",   "LUP", "Schedule H",   "Tablet",  "3004"),
        ("Telekast 10",     "1x10",   "GLE", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Omeprazole ─────────────────────────────────────────────────────
    ("Omeprazole 20mg", [
        ("Omez 20",         "1x10",   "DRL", "Schedule H",   "Capsule", "3004"),
        ("Prilosec 20",     "1x10",   "AUR", "Schedule H",   "Capsule", "3004"),
        ("Omesec 20",       "1x10",   "SUN", "Schedule H",   "Capsule", "3004"),
    ]),
    # ── Amlodipine ─────────────────────────────────────────────────────
    ("Amlodipine 5mg", [
        ("Amlong 5",        "10x10",  "MAN", "Schedule H",   "Tablet",  "3004"),
        ("Norvasc 5",       "10x10",  "PFZ", "Schedule H",   "Tablet",  "3004"),
        ("Amlopin 5",       "10x10",  "TOR", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Ibuprofen ──────────────────────────────────────────────────────
    ("Ibuprofen 400mg", [
        ("Brufen 400",      "1x10",   "ABT", "Schedule H",   "Tablet",  "3004"),
        ("Combiflam 400",   "1x20",   "SUN", "Schedule H",   "Tablet",  "3004"),
        ("Ibugesic 400",    "1x10",   "CIP", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Diclofenac ─────────────────────────────────────────────────────
    ("Diclofenac 50mg", [
        ("Voveran 50",      "1x10",   "WIN", "Schedule H",   "Tablet",  "3004"),
        ("Voltaren 50",     "1x10",   "PFZ", "Schedule H",   "Tablet",  "3004"),
        ("Reactin 50",      "1x10",   "MAN", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Ranitidine ─────────────────────────────────────────────────────
    ("Ranitidine 150mg", [
        ("Rantac 150",      "1x10",   "ALK", "Schedule H",   "Tablet",  "3004"),
        ("Zinetac 150",     "1x10",   "ABT", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Metronidazole ──────────────────────────────────────────────────
    ("Metronidazole 400mg", [
        ("Flagyl 400",      "1x10",   "ABT", "Schedule H",   "Tablet",  "3004"),
        ("Metrogyl 400",    "1x15",   "ZYD", "Schedule H",   "Tablet",  "3004"),
    ]),
    # ── Vitamin D3 ─────────────────────────────────────────────────────
    ("Cholecalciferol 60000 IU", [
        ("Uprise D3",       "4 caps", "ABT", "OTC",          "Capsule", "3004"),
        ("Calcirol 60000",  "4 caps", "CIP", "OTC",          "Capsule", "3004"),
    ]),
    # ── Vitamin B12 ────────────────────────────────────────────────────
    ("Methylcobalamin 500mcg", [
        ("Neurobion Forte", "1x30",   "MAN", "OTC",          "Tablet",  "3004"),
        ("Cobadex CZS",     "1x10",   "SUN", "OTC",          "Tablet",  "3004"),
        ("Polybion",        "1x10",   "ABT", "OTC",          "Tablet",  "3004"),
    ]),
    # ── Calcium + Vitamin D ────────────────────────────────────────────
    ("Calcium Carbonate 500mg + Vitamin D3 250IU", [
        ("Shelcal 500",     "1x10",   "TOR", "OTC",          "Tablet",  "3004"),
        ("Calcitas D",      "1x10",   "MAN", "OTC",          "Tablet",  "3004"),
    ]),
    # ── Antacid ────────────────────────────────────────────────────────
    ("Aluminium Hydroxide + Magnesium Hydroxide", [
        ("Digene Gel",      "200ml",  "ABT", "OTC",          "Syrup",   "3004"),
        ("Gelusil Syrup",   "200ml",  "PFZ", "OTC",          "Syrup",   "3004"),
    ]),
]


class Command(BaseCommand):
    help = "Seed realistic pharma products into local database for a given tenant"

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant", type=str, required=True,
            help="Tenant subdomain (e.g. 'pharmacy')"
        )

    def handle(self, *args, **options):
        subdomain = options["tenant"]
        try:
            tenant = Tenant.objects.get(subdomain=subdomain)
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant '{subdomain}' not found. Available: {list(Tenant.objects.values_list('subdomain', flat=True))}")

        self.stdout.write(f"Seeding products for tenant: {tenant.pharmacy_name}")

        # ── 1. Companies ────────────────────────────────────────────
        company_map = {}
        for sht, name in COMPANIES:
            obj, created = DrugCompany.objects.get_or_create(
                tenant=tenant, sht_name=sht,
                defaults={"company_name": name}
            )
            company_map[sht] = obj
        self.stdout.write(f"  ✓ {len(COMPANIES)} companies ready")

        # ── 2. Schedules ────────────────────────────────────────────
        schedule_map = {}
        for name in SCHEDULES:
            obj, _ = ProductSchedule.objects.get_or_create(tenant=tenant, schedule_name=name)
            schedule_map[name] = obj
        self.stdout.write(f"  ✓ {len(SCHEDULES)} schedules ready")

        # ── 3. Product Types ────────────────────────────────────────
        type_map = {}
        for name in TYPES:
            obj, _ = ProductType.objects.get_or_create(tenant=tenant, name=name)
            type_map[name] = obj
        self.stdout.write(f"  ✓ {len(TYPES)} product types ready")

        # ── 4. Default Tax (0%) ─────────────────────────────────────
        tax_obj, _ = ProductTax.objects.get_or_create(
            tenant=tenant, tax_name="GST 0%",
            defaults={"tax_rate": 0}
        )
        tax12, _ = ProductTax.objects.get_or_create(
            tenant=tenant, tax_name="GST 12%",
            defaults={"tax_rate": 12}
        )

        # ── 5. Products ─────────────────────────────────────────────
        created_count = 0
        for content_name, products in PRODUCTS_DATA:
            content_obj, _ = ProductContent.objects.get_or_create(
                tenant=tenant, content_name=content_name
            )
            for (pname, packing, company_sht, schedule, ptype, hsn) in products:
                _, created = Products.objects.get_or_create(
                    tenant=tenant,
                    product_name=pname,
                    defaults={
                        "product_packing": packing,
                        "product_content": content_obj,
                        "compny_name": company_map.get(company_sht),
                        "product_schedule": schedule_map.get(schedule),
                        "product_type": type_map.get(ptype),
                        "product_tax": tax_obj,
                        "product_hsn_code": hsn,
                        "conversion_factor": 10 if ptype in ("Tablet", "Capsule") and "x10" in packing else 1,
                    }
                )
                if created:
                    created_count += 1

        total = sum(len(p) for _, p in PRODUCTS_DATA)
        self.stdout.write(self.style.SUCCESS(
            f"  ✓ {created_count} new products created (skipped {total - created_count} existing)"
        ))
        self.stdout.write(self.style.SUCCESS("Done! Seed completed successfully."))
