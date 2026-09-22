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
    raw = config('GEMINI_API_KEY', default='') or os.getenv('GEMINI_API_KEY', '') or getattr(settings, 'GEMINI_API_KEY', '')
    if not raw:
        return []
    
    raw_keys = re.split(r'[,;\n\s]+', raw.strip())
    clean_keys = []
    for k in raw_keys:
        k = k.split('#')[0].strip().strip('"').strip("'")
        if k and len(k) > 15 and k not in clean_keys:
            clean_keys.append(k)
    return clean_keys

def _prepare_and_optimize_image(image_file, max_dimension=1600, quality=82):
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

def _call_ai_vision_api(api_keys, payload, timeout=45):
    """
    Calls the fastest active Gemini Vision endpoints with multi-key rotation,
    exponential backoff & jitter for 503 high demand spikes, and rapid key failover for 429 quota exhaustion.
    """
    if isinstance(api_keys, str):
        api_keys = [api_keys] if api_keys else []
    if not api_keys:
        api_keys = get_gemini_api_keys()

    if not api_keys:
        logger.error("No valid Gemini API key found.")
        raise ValueError("AI Bill Scanner service is not configured. Please add GEMINI_API_KEY in settings or .env.")

    # High-quota Free Tier models in order of speed and stability
    models_to_try = [
        ("v1beta", "gemini-3.1-flash-lite-preview"),  # Ultra fast, 1,000 req/day free
        ("v1beta", "gemini-3-flash-preview"),        # 250 req/day free
        ("v1beta", "gemini-3.1-flash-lite"),        # Fallback alias
        ("v1beta", "gemini-flash-lite-latest"),     # Dynamic latest
        ("v1beta", "gemini-3.5-flash-lite"),
        ("v1beta", "gemini-3.6-flash"),
        ("v1beta", "gemini-flash-latest"),
        ("v1beta", "gemini-3.5-flash"),
    ]

    headers = {'Content-Type': 'application/json'}
    last_error = None
    response = None

    for key_idx, api_key in enumerate(api_keys):
        for api_version, model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/{api_version}/models/{model_name}:generateContent?key={api_key}"
            
            # Max 2 attempts per model with exponential backoff on 503 (High Demand)
            max_retries = 2
            for attempt in range(max_retries):
                try:
                    res = requests.post(url, headers=headers, json=payload, timeout=timeout)
                    if res.status_code == 200:
                        response = res
                        break
                    elif res.status_code == 503:
                        # Temporary high demand on Google server - backoff with jitter
                        sleep_time = (1.5 * (attempt + 1)) + random.uniform(0.3, 0.8)
                        last_error = f"Key #{key_idx+1} {model_name} status 503 (High Demand). Retrying in {sleep_time:.2f}s..."
                        logger.warning(last_error)
                        time.sleep(sleep_time)
                    elif res.status_code == 429:
                        # Quota exceeded for this key, switch key immediately without retrying this key
                        last_error = f"Key #{key_idx+1} {model_name} status 429 (Quota exceeded)"
                        logger.warning(last_error)
                        break
                    elif res.status_code == 404:
                        # Model name not supported on this endpoint version
                        last_error = f"Key #{key_idx+1} {model_name} status 404 (Not Found)"
                        break
                    else:
                        last_error = f"Key #{key_idx+1} {model_name} status {res.status_code}: {res.text[:150]}"
                        logger.warning(f"AI Vision attempt error: {last_error}")
                        break
                except requests.exceptions.Timeout:
                    last_error = f"Key #{key_idx+1} {model_name} timed out after {timeout}s"
                    logger.warning(last_error)
                    break
                except Exception as e:
                    last_error = f"Key #{key_idx+1} {model_name} exception: {str(e)}"
                    logger.warning(f"AI Vision request exception: {last_error}")
                    break

            if response and response.status_code == 200:
                break
        if response and response.status_code == 200:
            break

    if not response or response.status_code != 200:
        logger.error(f"AI Vision request failed across all keys and models. Last details: {last_error}")
        raise Exception("AI OCR engine is currently busy or unable to process this document. Please ensure the image is clear and try again.")

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
        "Carefully parse this purchase bill image and extract all details with extreme precision:\n\n"
        "1. Supplier/Vendor name (distributor/wholesaler selling the medicines)\n"
        "2. Invoice number (bill number or reference number)\n"
        "3. Purchase/Invoice date (YYYY-MM-DD format if visible, or original text date converted to standard date)\n"
        "4. Payment mode ('Cash' or 'Credit' if visible, default to 'Cash')\n"
        "5. Line items (medicines/products table). For each item on EVERY row:\n"
        "   - name: Medicine or product name with brand & strength/dosage (e.g. 'Pantocid 40mg', 'Augmentin 625 Duo', 'Telma 40'). Remove leading serial numbers (e.g., '1.', '2.') or stray symbols.\n"
        "   - batch_number: Exact batch number on this specific line (e.g. 'B2401', 'BT24110', 'T-5421', 'NX205').\n"
        "     * CRITICAL FOR BATCH: Maintain strict 1-to-1 horizontal row alignment. Each batch must match ONLY its corresponding row item. Do NOT shift batch numbers across adjacent rows. If a row lacks a batch, return null.\n"
        "     * Do not confuse HSN codes, dates, or prices with batch numbers.\n"
        "   - expiry_date: Expiry date (convert to MM/YYYY or YYYY-MM-DD format. E.g. '06/27' -> '06/2027', '04/28' -> '04/2028', '11-26' -> '11/2026'). Expiry represents future dates.\n"
        "   - quantity: Exact billed/purchased quantity.\n"
        "     * CRITICAL FOR QUANTITY: Read every single digit with extreme care. NEVER truncate or drop digits (e.g., if quantity is '24', extract exactly 24, NOT 2; if '120', extract 120, NOT 12). Read the main billed quantity column (Billed Qty / Qty / Invoiced Qty).\n"
        "     * Do not confuse Pack Size (e.g. 10TAB, 1x10, 10's) or Scheme/Free qty with the main Quantity column.\n"
        "   - free_quantity: Free/scheme quantity received (e.g. if '24 + 2' or Free column is '2', free_quantity is 2. Default to 0 if none).\n"
        "   - purchase_price: Purchase rate/price per unit/pack excluding GST tax (or standard billing rate).\n"
        "   - mrp: Maximum Retail Price (MRP) per pack/box/strip.\n"
        "   - tax_percentage: GST tax rate percentage (e.g. 5, 12, 18. Default to 12 if not explicitly stated).\n"
        "   - total: Net line amount for this row (quantity * purchase_price, or bill line amount).\n\n"
        "Output MUST be a valid JSON object matching this schema:\n"
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
        raise Exception("Unable to parse bill structure. Please ensure the document is clear and try again.")

    # Parse and clean JSON
    cleaned_text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
    if match:
        cleaned_text = match.group(1)

    try:
        parsed_data = json.loads(cleaned_text.strip())
        return parsed_data
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode failed for AI OCR output: {cleaned_text}. Error: {e}")
        raise Exception("Could not extract structured data from this document. Please ensure the image is clear.")


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
