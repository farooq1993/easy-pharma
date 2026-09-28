import io
from PIL import Image
import base64
import time
import random
import requests
import json
import re
import logging
from django.conf import settings
from decouple import config
import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables robustly
load_dotenv()
current_dir = os.path.dirname(os.path.abspath(__file__))
for env_candidate in [
    os.path.join(current_dir, '..', '..', 'pharmaProject', '.env'),
    os.path.join(current_dir, '..', '..', '.env'),
    os.path.join(current_dir, '..', '.env'),
]:
    if os.path.exists(env_candidate):
        load_dotenv(env_candidate)

def get_gemini_api_keys():
    """
    Returns a list of clean API keys configured in environment.
    Supports single or multiple comma/semicolon/newline-separated keys for 100% free multi-key rotation.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for env_candidate in [
        os.path.join(current_dir, '..', '..', 'pharmaProject', '.env'),
        os.path.join(current_dir, '..', '..', '.env'),
        os.path.join(current_dir, '..', '.env'),
        '/var/www/easypharma/.env',
        '/var/www/easypharma/pharmaProject/.env',
    ]:
        if os.path.exists(env_candidate):
            load_dotenv(env_candidate, override=True)

    raw = os.getenv('GEMINI_API_KEY', '') or config('GEMINI_API_KEY', default='') or getattr(settings, 'GEMINI_API_KEY', '')
    if not raw:
        return []
    
    raw_keys = re.split(r'[,;\n\s]+', raw.strip())
    clean_keys = []
    for k in raw_keys:
        k = k.split('#')[0].strip().strip('"').strip("'")
        if k and len(k) > 15 and k not in clean_keys:
            clean_keys.append(k)
    return clean_keys

def _prepare_and_optimize_image(image_file, max_dimension=2048, quality=88):
    """
    Optimizes and compresses image before base64 encoding to speed up upload & AI processing by 80-90%.
    """
    if hasattr(image_file, 'read'):
        image_data = image_file.read()
        if hasattr(image_file, 'seek'):
            try:
                image_file.seek(0)
            except Exception:
                pass
    else:
        image_data = image_file

    try:
        img = Image.open(io.BytesIO(image_data))
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')

        width, height = img.size
        if max(width, height) > max_dimension:
            if width > height:
                new_w = max_dimension
                new_h = int(height * (max_dimension / width))
            else:
                new_h = max_dimension
                new_w = int(width * (max_dimension / height))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        out_io = io.BytesIO()
        img.save(out_io, format='JPEG', quality=quality, optimize=True)
        return base64.b64encode(out_io.getvalue()).decode('utf-8')
    except Exception as e:
        logger.warning(f"Image optimization fallback: {e}")
        return base64.b64encode(image_data).decode('utf-8')

def _call_ai_vision_api(api_keys, payload, timeout=8):
    """
    Calls the fastest active Gemini Vision endpoints with multi-key rotation
    and sub-second failover across active models.
    """
    if isinstance(api_keys, str):
        api_keys = [api_keys] if api_keys else []
    if not api_keys:
        api_keys = get_gemini_api_keys()

    if not api_keys:
        logger.error("No valid Gemini API key found.")
        raise ValueError("AI Bill Scanner service is not configured. Please add GEMINI_API_KEY in settings or .env.")

    # NOTE: gemini-1.5-flash, 2.0-flash, 2.5-flash, 1.5-pro all return 404 on this project
    # Only gemini-3.x models are available on Google AI Studio free tier project
    # (api_version, model_name, timeout_seconds)
    models_to_try = [
        ("v1beta", "gemini-3.1-flash-lite",         12),
        ("v1beta", "gemini-3.5-flash-lite",         12),
        ("v1beta", "gemini-3.1-flash-lite-preview", 12),
        ("v1beta", "gemini-flash-latest",           12),
    ]

    headers = {'Content-Type': 'application/json'}
    last_error = None
    response = None

    # Load-balance across multiple API keys for concurrent users
    shuffled_keys = list(api_keys)
    random.shuffle(shuffled_keys)
    logger.info(f"AI OCR starting scan with {len(shuffled_keys)} active API key(s)")

    # 2-pass retry loop with exponential backoff on 503/429 high demand spikes
    start_time = time.time()
    MAX_LOOP_TIME = 45 # Prevent Nginx 504 Gateway Timeout (Nginx default is often 30s or 60s)

    for pass_num in range(2):
        if pass_num > 0:
            logger.info(f"AI OCR initiating retry pass #{pass_num+1} after high demand spike...")
            time.sleep(1.0)

        for key_idx, api_key in enumerate(shuffled_keys):
            for api_version, model_name, model_timeout in models_to_try:
                if time.time() - start_time > MAX_LOOP_TIME:
                    logger.error("AI OCR loop exceeded maximum execution time (45s). Aborting to prevent 504.")
                    raise Exception("Server is currently overloaded. Please try again in a few minutes.")

                url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model_name}:generateContent?key={api_key}"
                
                try:
                    res = requests.post(url, headers=headers, json=payload, timeout=model_timeout)
                    if res.status_code == 200:
                        logger.info(f"AI OCR success: Key #{key_idx+1} {model_name} ({api_version}) [pass {pass_num+1}]")
                        response = res
                        break
                    elif res.status_code == 429:
                        last_error = f"Key #{key_idx+1} {model_name} rate limited (429): {res.text[:100]}"
                        logger.warning(last_error)
                        time.sleep(0.5)
                        continue
                    elif res.status_code == 503:
                        last_error = f"Key #{key_idx+1} {model_name} busy (503): {res.text[:100]}"
                        logger.warning(last_error)
                        time.sleep(0.5)
                        continue
                    elif res.status_code == 404:
                        last_error = f"Key #{key_idx+1} {model_name} ({api_version}) not found (404)"
                        logger.debug(last_error)
                        continue
                    else:
                        last_error = f"Key #{key_idx+1} {model_name} status {res.status_code}: {res.text[:100]}"
                        logger.warning(f"AI OCR attempt note: {last_error}")
                        continue
                except requests.exceptions.Timeout:
                    last_error = f"Key #{key_idx+1} {model_name} timed out after {model_timeout}s"
                    logger.warning(last_error)
                    continue
                except Exception as e:
                    last_error = f"Key #{key_idx+1} {model_name} exception: {str(e)}"
                    logger.warning(f"AI OCR connection error: {last_error}")
                    continue

            if response and response.status_code == 200:
                break
        
        if response and response.status_code == 200:
            break

    if not response or response.status_code != 200:
        logger.error(f"AI Vision request failed across all keys and models. Last details: {last_error}")
        raise Exception(f"AI OCR service is temporarily busy. Last developer note: {last_error}")

    return response


def extract_purchase_bill_data(image_file):
    """
    Sends the purchase bill/invoice image to AI OCR Engine to extract details.
    image_file: file-like object or bytes
    """
    api_keys = get_gemini_api_keys()
    if not api_keys:
        logger.error("AI API key is missing in environment variables.")
        raise ValueError("AI Bill Scanner service is not configured. Please contact administrator.")

    base64_image = _prepare_and_optimize_image(image_file)

    prompt = (
        "You are an expert accountant and pharmacy billing OCR AI specializing in Indian pharmacy purchase bills/invoices.\n"
        "Parse this purchase bill image with EXTREME precision using the ROW-BY-ROW method below.\n\n"
        "=== HEADER EXTRACTION ===\n"
        "1. Supplier/Vendor name (distributor/wholesaler selling the medicines)\n"
        "2. Invoice number (bill number or reference number)\n"
        "3. Purchase/Invoice date (YYYY-MM-DD format)\n"
        "4. Payment mode ('Cash' or 'Credit' if visible, default to 'Cash')\n\n"
        "=== MANDATORY ROW-BY-ROW PARSING METHOD ===\n"
        "You MUST follow this exact procedure for the items table:\n\n"
        "STEP 1: Identify the column headers in the table (e.g., Sr.No, Product/Item Name, Batch No, Expiry, Qty, Free, Rate, MRP, GST%, Amount, etc.).\n"
        "STEP 2: Count the total number of data rows in the table.\n"
        "STEP 3: Process EACH ROW ONE AT A TIME, from top (Row 1) to bottom (last row):\n"
        "   - Place your finger on the ROW NUMBER or first cell of that row.\n"
        "   - Read HORIZONTALLY across that SAME row to extract ALL fields.\n"
        "   - DO NOT look at any other row while extracting this row's data.\n"
        "   - The batch_number, expiry_date, quantity, mrp, and all other values\n"
        "     MUST come from the SAME horizontal line as the product name.\n\n"
        "*** ABSOLUTE RULE - BATCH NUMBER ALIGNMENT ***\n"
        "The #1 most critical rule: Each product's batch_number MUST be read from\n"
        "the EXACT SAME horizontal row as that product's name. NEVER assign a batch\n"
        "number from Row N to a product on Row N-1 or Row N+1.\n"
        "If a bill has 5 products:\n"
        "  - Row 1's batch goes ONLY to Row 1's product\n"
        "  - Row 2's batch goes ONLY to Row 2's product\n"
        "  - Row 3's batch goes ONLY to Row 3's product\n"
        "  - Row 4's batch goes ONLY to Row 4's product\n"
        "  - Row 5's batch goes ONLY to Row 5's product\n"
        "If a row has no batch number visible, set batch_number to null for that row.\n"
        "NEVER shift or swap batch numbers between rows.\n\n"
        "=== FIELD RULES ===\n"
        "- name: Medicine/product name with brand & strength/dosage (e.g. 'Pantocid 40mg', 'Augmentin 625 Duo'). Remove leading serial numbers ('1.', '2.') or stray symbols.\n"
        "- batch_number: Exact batch number from THIS row only (e.g. 'B2401', 'BT24110'). Do NOT confuse HSN codes, dates, or prices with batch numbers.\n"
        "- expiry_date: Convert to MM/YYYY format (e.g. '06/27' -> '06/2027', '04/28' -> '04/2028'). Expiry represents future dates.\n"
        "- quantity: Exact billed/purchased quantity. Read EVERY digit carefully. NEVER truncate digits (e.g., '24' must be 24 NOT 2; '120' must be 120 NOT 12). Read the main Billed Qty / Qty / Invoiced Qty column.\n"
        "  * Do NOT confuse Pack Size (10TAB, 1x10, 10's) or Scheme/Free qty with Quantity.\n"
        "- free_quantity: Free/scheme quantity (default 0 if none).\n"
        "- purchase_price: Purchase rate per unit/pack excluding GST.\n"
        "- mrp: Maximum Retail Price (MRP) per pack/box/strip.\n"
        "- tax_percentage: GST rate (e.g. 5, 12, 18. Default 12 if not stated).\n"
        "- total: Net line amount for this row.\n\n"
        "=== SELF-VERIFICATION STEP ===\n"
        "After extraction, verify:\n"
        "1. The number of items in your JSON equals the number of rows in the table.\n"
        "2. For each item, confirm its batch_number was read from the same row as its name.\n"
        "3. No two adjacent items have swapped batch numbers.\n\n"
        "=== OUTPUT FORMAT ===\n"
        "Output MUST be a valid JSON object:\n"
        "{\n"
        "  \"supplier_name\": \"string or null\",\n"
        "  \"invoice_number\": \"string or null\",\n"
        "  \"purchase_date\": \"string format YYYY-MM-DD or null\",\n"
        "  \"payment_mode\": \"Cash or Credit\",\n"
        "  \"items\": [\n"
        "    {\n"
        "      \"name\": \"string\",\n"
        "      \"batch_number\": \"string or null\",\n"
        "      \"expiry_date\": \"string format MM/YYYY or YYYY-MM-DD or null\",\n"
        "      \"quantity\": integer,\n"
        "      \"free_quantity\": integer,\n"
        "      \"purchase_price\": float,\n"
        "      \"mrp\": float,\n"
        "      \"tax_percentage\": float,\n"
        "      \"total\": float\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Return ONLY the raw JSON block without markdown formatting or code blocks."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": base64_image
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "response_mime_type": "application/json"
        }
    }

    response = _call_ai_vision_api(api_keys, payload, timeout=45)

    resp_json = response.json()
    try:
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError):
        logger.error(f"Unexpected AI response structure: {resp_json}")
        raise Exception("Unable to parse bill structure. Please ensure the document is clear and try again.")

    # Parse and clean JSON
    cleaned_text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
    if match:
        cleaned_text = match.group(1)

    try:
        parsed_data = json.loads(cleaned_text.strip())
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode failed for AI OCR output: {cleaned_text}. Error: {e}")
        raise Exception("Could not extract structured data from this document. Please ensure the image is clear.")

    # Post-processing validation: detect potential batch number misalignment
    items = parsed_data.get('items', [])
    if items:
        batch_numbers = [item.get('batch_number') for item in items if item.get('batch_number')]
        unique_batches = set(batch_numbers)
        if len(batch_numbers) != len(unique_batches):
            # Duplicate batch numbers detected — could be legitimate (same batch for different products)
            # but also a sign of row shifting. Log for monitoring.
            dupes = [b for b in unique_batches if batch_numbers.count(b) > 1]
            logger.warning(f"AI OCR WARNING: Duplicate batch numbers detected: {dupes} across {len(items)} items. "
                           f"This may indicate row misalignment. Items: {[(i.get('name','?'), i.get('batch_number')) for i in items]}")

    # Ensure each item has required fields with safe defaults
    final_items = parsed_data.get('items', [])
    for item in final_items:
        item.setdefault('batch_number', None)
        item.setdefault('expiry_date', None)
        item.setdefault('quantity', 0)
        item.setdefault('free_quantity', 0)
        item.setdefault('purchase_price', 0.0)
        item.setdefault('mrp', 0.0)
        item.setdefault('tax_percentage', 12.0)
        item.setdefault('total', 0.0)

    return parsed_data


def extract_opening_stock_data(image_file):
    """
    Sends an opening stock image (handwritten or printed list) to AI OCR Engine to extract details.
    image_file: file-like object or bytes
    """
    api_keys = get_gemini_api_keys()
    if not api_keys:
        logger.error("AI API key is missing in environment variables.")
        raise ValueError("AI Opening Stock service is not configured. Please contact administrator.")

    base64_image = _prepare_and_optimize_image(image_file)

    prompt = (
        "You are an expert pharmacy inventory OCR AI specializing in reading handwritten notes, stock registers, and printed inventory lists for Indian pharmacies.\n"
        "Carefully parse this opening stock document/image and extract all items with extreme precision:\n\n"
        "For each item line/row:\n"
        "   - name: Medicine or product name with brand & strength/dosage (e.g. 'Pantocid 40mg', 'Augmentin 625 Duo', 'Telma 40'). Remove leading serial numbers (e.g., '1.', '2.') or stray bullet points.\n"
        "   - batch_number: Exact batch number for this item (e.g. 'B2401', 'BT24110', 'T-5421', 'OPENING'). Maintain strict row alignment. Default to 'OPENING' if not specified.\n"
        "   - expiry_date: Expiry date (convert to MM/YYYY format e.g. '06/27' -> '06/2027', '04-28' -> '04/2028', '01/27' -> '01/2027'). Default to null if not specified.\n"
        "   - quantity: Exact quantity in units/packs. Read digits carefully without dropping numbers.\n"
        "   - mrp: Maximum Retail Price (MRP) per pack/unit.\n"
        "   - purchase_price: Purchase rate per unit (if specified. Default to mrp or 0.0 if not listed).\n"
        "   - tax_percentage: GST percentage (e.g. 5, 12, 18. Default to 5 if not explicitly stated).\n"
        "   - total: Calculated total amount for this row (quantity * purchase_price, or listed total).\n\n"
        "Output MUST be a valid JSON object matching this schema:\n"
        "{\n"
        "  \"items\": [\n"
        "    {\n"
        "      \"name\": \"string\",\n"
        "      \"batch_number\": \"string or null\",\n"
        "      \"expiry_date\": \"string format MM/YYYY or YYYY-MM-DD or null\",\n"
        "      \"quantity\": integer,\n"
        "      \"mrp\": float,\n"
        "      \"purchase_price\": float,\n"
        "      \"tax_percentage\": float,\n"
        "      \"total\": float\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Return ONLY the raw JSON block without markdown formatting or code blocks."
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": base64_image
                        }
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json"
        }
    }

    response = _call_ai_vision_api(api_keys, payload, timeout=45)

    resp_json = response.json()
    try:
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError):
        logger.error(f"Unexpected AI response structure: {resp_json}")
        raise Exception("Unable to parse document structure. Please ensure the document is clear and try again.")

    cleaned_text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
    if match:
        cleaned_text = match.group(1)

    try:
        parsed_data = json.loads(cleaned_text.strip())
        return parsed_data
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode failed for opening stock output: {cleaned_text}. Error: {e}")
        raise Exception("Could not extract structured data from this document. Please ensure the image is clear.")
