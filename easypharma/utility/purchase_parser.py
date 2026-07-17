import base64
import json
import re
import os
import requests
from django.conf import settings
from dotenv import load_dotenv

# Try loading env variables
load_dotenv()
current_dir = os.path.dirname(os.path.abspath(__file__))
inner_env_path = os.path.join(current_dir, '..', '..', 'pharmaProject', '.env')
if os.path.exists(inner_env_path):
    load_dotenv(inner_env_path)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', default='')

def parse_supplier_invoice(file_data, mime_type='application/pdf'):
    """
    Sends the supplier invoice file (PDF/Image) to Gemini to extract billing metadata and items.
    file_data: bytes of the file
    mime_type: MIME type of the file (e.g., 'application/pdf', 'image/jpeg', 'image/png')
    """
    api_key = GEMINI_API_KEY
    if not api_key:
        raise ValueError("Gemini API key is not configured. Please set GEMINI_API_KEY in environment variables.")

    base64_data = base64.b64encode(file_data).decode('utf-8')

    prompt = (
        "You are an expert pharma accountant. Analyze this supplier invoice/purchase bill (which could be a PDF or an image) and extract the invoice details and all line items.\n\n"
        "Please extract the following information:\n"
        "1. Supplier's Name (e.g. distributor name)\n"
        "2. Supplier's GSTIN (GST number, 15 characters, starts with 2 digits state code)\n"
        "3. Invoice/Bill Number\n"
        "4. Invoice Date (Format: YYYY-MM-DD. If year is missing, assume current year 2026)\n"
        "5. Sub Total (total taxable value before tax)\n"
        "6. Tax Amount (total GST/CGST/SGST/IGST)\n"
        "7. Total Invoice Amount\n"
        "8. List of items. For each item, extract:\n"
        "   - raw_product_name: The name of the medicine exactly as printed on the bill (e.g., 'Pan-D Capsule', 'Taxim-O 200mg')\n"
        "   - batch_number: The Batch Number (often labeled as Batch, B.No, B.Number)\n"
        "   - expiry_date: Expiry Date (Convert to YYYY-MM-DD format. If only MM/YY or MM/YYYY is printed, set it to the last day of that month, e.g., '12/28' or '12/2028' becomes '2028-12-31')\n"
        "   - quantity: Purchased quantity (number of boxes/strips/units)\n"
        "   - free_quantity: Free quantity (often labeled as Free, Scheme, F.Qty). Default to 0 if not present.\n"
        "   - purchase_price: Purchase rate/cost price per unit before GST\n"
        "   - mrp: Maximum Retail Price per unit printed on the invoice\n"
        "   - sale_price: Expected sale price (default to MRP if not separately specified)\n"
        "   - tax_percentage: GST tax rate percentage (e.g. 5, 12, 18, 28, or 12.00)\n"
        "   - total_amount: Total purchase amount for this item line (excluding tax, i.e., quantity * purchase_price)\n\n"
        "Output MUST be a valid JSON object matching this schema:\n"
        "{\n"
        "  \"supplier_name\": \"string\",\n"
        "  \"supplier_gstin\": \"string or null\",\n"
        "  \"invoice_number\": \"string\",\n"
        "  \"invoice_date\": \"string or null\",\n"
        "  \"sub_total\": float,\n"
        "  \"tax_amount\": float,\n"
        "  \"total_amount\": float,\n"
        "  \"items\": [\n"
        "    {\n"
        "      \"raw_product_name\": \"string\",\n"
        "      \"batch_number\": \"string\",\n"
        "      \"expiry_date\": \"string\",\n"
        "      \"quantity\": integer,\n"
        "      \"free_quantity\": integer,\n"
        "      \"purchase_price\": float,\n"
        "      \"mrp\": float,\n"
        "      \"sale_price\": float,\n"
        "      \"tax_percentage\": float,\n"
        "      \"total_amount\": float\n"
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
                            "mimeType": mime_type,
                            "data": base64_data
                        }
                    }
                ]
            }
        ]
    }

    max_retries = 3
    for attempt in range(max_retries):
        response = requests.post(url, headers=headers, json=payload, timeout=40)
        # If Gemini is busy (503), retry after a short delay
        if response.status_code == 503 and attempt < max_retries - 1:
            import time
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

    # Parse and clean JSON response
    cleaned_text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
    if match:
        cleaned_text = match.group(1)

    try:
        parsed_data = json.loads(cleaned_text.strip())
        return parsed_data
    except json.JSONDecodeError as e:
        raise Exception(f"Failed to parse Gemini output as JSON: {cleaned_text}. Error: {str(e)}")
