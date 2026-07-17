import imaplib
import email
from email.header import decode_header
import os
import mimetypes
from datetime import datetime
from django.conf import settings
from django.utils import timezone
from easypharma.models.email_config import EmailConfig
from easypharma.models.draft_purchase import DraftPurchaseInvoice, DraftPurchaseItem
from easypharma.models.purchase_invoice import PurchaseInvoice
from easypharma.models.Items import Products
from easypharma.utility.purchase_parser import parse_supplier_invoice

def sync_all_tenant_emails():
    """
    Cron / Celery job endpoint. Syncs emails for all active EmailConfig records.
    """
    active_configs = EmailConfig.objects.filter(is_active=True)
    results = []
    for config in active_configs:
        print(f"Starting email sync for: {config.email_address} (Tenant: {config.tenant.id})")
        count = fetch_and_process_emails(config)
        results.append({
            'email': config.email_address,
            'tenant_id': config.tenant.id,
            'imported': count
        })
        config.last_sync = timezone.now()
        config.save()
    return results

def fetch_and_process_emails(config):
    """
    Connects to Gmail via IMAP and processes unread invoices.
    """
    imported_count = 0
    try:
        # Connect to Gmail IMAP
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(config.email_address, config.app_password)
        mail.select("INBOX")

        # Search for unseen (unread) emails
        # We search for UNSEEN emails
        status, messages = mail.uid('search', None, 'UNSEEN')
        if status != 'OK':
            print("No UNSEEN messages found or IMAP error.")
            return 0

        uids = messages[0].split()
        print(f"Found {len(uids)} unread emails.")

        for uid in uids:
            # Fetch email headers and parts
            res, msg_data = mail.uid('fetch', uid, '(RFC822)')
            if res != 'OK':
                continue

            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    raw_email = response_part[1]
                    msg = email.message_from_bytes(raw_email)
                    
                    subject, encoding = decode_header(msg["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding or "utf-8", errors="ignore")
                    
                    subject_lower = subject.lower()
                    
                    # Basic filters to skip non-invoice emails quickly
                    # (optional but recommended to avoid useless API calls)
                    invoice_keywords = ['invoice', 'bill', 'purchase', 'tax invoice', 'gst', 'receipt', 'payment']
                    has_keyword = any(kw in subject_lower for kw in invoice_keywords)
                    
                    print(f"Checking Email Subject: '{subject}' (has_keyword: {has_keyword})")
                    
                    # Walk parts to find PDF or Image attachments
                    attachments_found = []
                    for part in msg.walk():
                        if part.get_content_maintype() == 'multipart':
                            continue
                        if part.get('Content-Disposition') is None:
                            continue
                            
                        filename = part.get_filename()
                        if filename:
                            filename_decoded, encoding = decode_header(filename)[0]
                            if isinstance(filename_decoded, bytes):
                                filename_decoded = filename_decoded.decode(encoding or "utf-8", errors="ignore")
                            
                            ext = os.path.splitext(filename_decoded)[1].lower()
                            if ext in ['.pdf', '.jpg', '.jpeg', '.png']:
                                attachments_found.append((part, filename_decoded, ext))

                    if not attachments_found:
                        continue

                    # Process each valid attachment
                    for part, filename, ext in attachments_found:
                        file_bytes = part.get_payload(decode=True)
                        if not file_bytes:
                            continue

                        mime_type, _ = mimetypes.guess_type(filename)
                        if not mime_type:
                            if ext == '.pdf':
                                mime_type = 'application/pdf'
                            else:
                                mime_type = 'image/jpeg'

                        print(f"Processing attachment: {filename} ({mime_type})")
                        try:
                            # 1. Parse using Gemini
                            invoice_data = parse_supplier_invoice(file_bytes, mime_type)
                            inv_number = invoice_data.get('invoice_number', '').strip()
                            supplier_name = invoice_data.get('supplier_name', '').strip()
                            supplier_gstin = invoice_data.get('supplier_gstin', '').strip() if invoice_data.get('supplier_gstin') else None

                            if not inv_number or not supplier_name:
                                print("Skipping attachment: could not extract basic invoice metadata.")
                                continue

                            # 2. Check for duplicate invoice in regular purchases and draft purchases
                            is_duplicate = PurchaseInvoice.objects.filter(
                                tenant=config.tenant,
                                invoice_number=inv_number,
                                supplier__name__iexact=supplier_name
                            ).exists() or DraftPurchaseInvoice.objects.filter(
                                tenant=config.tenant,
                                invoice_number=inv_number,
                                supplier_name__iexact=supplier_name
                            ).exists()

                            if is_duplicate:
                                print(f"Skipping duplicate invoice: {inv_number} from {supplier_name}")
                                continue

                            # 3. Save invoice attachment file locally
                            media_dir = os.path.join(settings.MEDIA_ROOT, 'purchase_invoices')
                            os.makedirs(media_dir, exist_ok=True)
                            unique_filename = f"{config.tenant.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
                            file_path = os.path.join(media_dir, unique_filename)
                            with open(file_path, 'wb') as f:
                                f.write(file_bytes)

                            # 4. Create Draft Invoice
                            inv_date_str = invoice_data.get('invoice_date')
                            inv_date = None
                            if inv_date_str:
                                try:
                                    inv_date = datetime.strptime(inv_date_str, '%Y-%m-%d').date()
                                except ValueError:
                                    inv_date = timezone.now().date()

                            draft_invoice = DraftPurchaseInvoice.objects.create(
                                tenant=config.tenant,
                                supplier_name=supplier_name,
                                supplier_gstin=supplier_gstin,
                                invoice_number=inv_number,
                                invoice_date=inv_date,
                                sub_total=invoice_data.get('sub_total', 0.0),
                                tax_amount=invoice_data.get('tax_amount', 0.0),
                                total_amount=invoice_data.get('total_amount', 0.0),
                                attachment_path=f"purchase_invoices/{unique_filename}",
                                status='Pending'
                            )

                            # 5. Create Draft Items and match with existing products
                            for item in invoice_data.get('items', []):
                                raw_name = item.get('raw_product_name', '').strip()
                                
                                # Try matching raw name with existing database products
                                matched_product = None
                                if raw_name:
                                    # Strict check, case-insensitive
                                    matched_product = Products.objects.filter(
                                        tenant=config.tenant,
                                        product_name__iexact=raw_name
                                    ).first()
                                    
                                    # Fallback: substring match if strict fails
                                    if not matched_product:
                                        matched_product = Products.objects.filter(
                                            tenant=config.tenant,
                                            product_name__icontains=raw_name
                                        ).first()

                                item_date_str = item.get('expiry_date')
                                item_exp_date = None
                                if item_date_str:
                                    try:
                                        item_exp_date = datetime.strptime(item_date_str, '%Y-%m-%d').date()
                                    except ValueError:
                                        pass

                                DraftPurchaseItem.objects.create(
                                    tenant=config.tenant,
                                    draft_invoice=draft_invoice,
                                    raw_product_name=raw_name,
                                    matched_product=matched_product,
                                    batch_number=item.get('batch_number', 'BATCH').strip(),
                                    expiry_date=item_exp_date,
                                    quantity=int(item.get('quantity', 0)),
                                    free_quantity=int(item.get('free_quantity', 0)),
                                    purchase_price=item.get('purchase_price', 0.0),
                                    mrp=item.get('mrp', 0.0),
                                    sale_price=item.get('sale_price', item.get('mrp', 0.0)),
                                    tax_percentage=item.get('tax_percentage', 0.0),
                                    total_amount=item.get('total_amount', 0.0)
                                )

                            imported_count += 1
                            print(f"Successfully imported draft invoice: {inv_number}")

                        except Exception as parse_err:
                            print(f"Error parsing attachment {filename}: {parse_err}")

            # Mark email as read once processed
            mail.uid('store', uid, '+FLAGS', '\\Seen')

        mail.logout()
    except Exception as e:
        print(f"IMAP sync failed: {e}")

    return imported_count
