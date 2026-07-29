import base64
import time
import requests
import json
import re
from django.conf import settings
from decouple import config
import os
from dotenv import load_dotenv

# Try standard dotenv load
load_dotenv()

# Also try loading specifically from the inner settings folder
current_dir = os.path.dirname(os.path.abspath(__file__))
inner_env_path = os.path.join(current_dir, '..', '..', 'pharmaProject', '.env')
if os.path.exists(inner_env_path):
    load_dotenv(inner_env_path)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', default='')

def extract_purchase_bill_data(image_file):
    """
    Sends the purchase bill/invoice image to Gemini API to extract details.
    image_file: file-like object or bytes
    """
    api_key = GEMINI_API_KEY
    if api_key:
        api_key = api_key.split('#')[0].strip().split()[0]
    
    if not api_key:
        raise ValueError("Gemini API key is not configured. Please set GEMINI_API_KEY in environment variables.")

    # Read image bytes
    if hasattr(image_file, 'read'):
        image_data = image_file.read()
    else:
        image_data = image_file

    base64_image = base64.b64encode(image_data).decode('utf-8')

    prompt = (
        "You are an expert accountant and pharmacy billing AI. Parse this purchase bill (invoice) image and extract the following details:\n"
        "1. Supplier/Vendor name (the distributor or company selling the medicines)\n"
        "2. Invoice number (bill number or invoice reference number)\n"
        "3. Purchase/Invoice date (in YYYY-MM-DD format if visible)\n"
        "4. Payment mode (detect 'Cash' or 'Credit' if visible, default to 'Cash')\n"
        "5. List of line items (medicines/products). For each item, extract:\n"
        "   - name: The product or medicine name (e.g. 'Pantocid 40mg', 'Augmentin 625 Duo'). Clean up prefixes or stray characters, but keep the core brand name and dosage.\n"
        "   - batch_number: The batch number of the item (e.g. 'B2401', 'T-5421').\n"
        "   - expiry_date: Expiry date (convert to YYYY-MM-DD or MM/YYYY format. If MM/YY is on bill, convert YY to 4 digits like MM/YYYY, e.g. 06/27 to 06/2027. Expiry should always be future date, e.g., if 26 is written, it represents 2026).\n"
        "   - quantity: Purchased quantity (number of packs/boxes/strips/units as represented in the main quantity column).\n"
        "   - free_quantity: Free quantity received (default to 0 if not present or 0).\n"
        "   - purchase_price: Purchase price per pack/box/strip (unit rate excluding tax, or standard purchase rate/price).\n"
        "   - mrp: Maximum Retail Price (MRP) per pack/box/strip.\n"
        "   - tax_percentage: GST tax rate percentage applied (e.g. 5, 12, 18, 28. Default to 12 if not clear).\n"
        "   - total: Total line amount for the quantity (quantity * purchase_price, or invoice line amount).\n\n"
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
        "      \"expiry_date\": \"string format YYYY-MM-DD or MM/YYYY or null\",\n"
        "      \"quantity\": integer,\n"
        "      \"free_quantity\": integer,\n"
        "      \"purchase_price\": float,\n"
        "      \"mrp\": float,\n"
        "      \"tax_percentage\": float,\n"
        "      \"total\": float\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Return ONLY the raw JSON block. Do not include markdown code fence formatting (like ```json ... ```) or any other text."
    )

    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-3.1-flash-lite:generateContent?key={api_key}"
    headers = {'Content-Type': 'application/json'}
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
        ]
    }

    max_retries = 3
    for attempt in range(max_retries):
        response = requests.post(url, headers=headers, json=payload, timeout=40)
        # If Gemini is busy (503) or rate-limited (429), retry after a short delay
        if response.status_code in [429, 503] and attempt < max_retries - 1:
            time.sleep(2.0)
            continue
        break

    if response.status_code != 200:
        raise Exception(f"Gemini API request failed with status code {response.status_code}: {response.text}")

    resp_json = response.json()
    try:
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError):
        raise Exception(f"Invalid response format from Gemini API: {resp_json}")

    # Parse and clean JSON
    cleaned_text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
    if match:
        cleaned_text = match.group(1)

    try:
        parsed_data = json.loads(cleaned_text.strip())
        return parsed_data
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse Gemini output as JSON: {cleaned_text}. Error: {str(e)}")
