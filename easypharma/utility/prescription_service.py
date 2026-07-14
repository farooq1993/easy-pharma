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

# Also try loading specifically from the inner settings folder (pharmaProject/pharmaProject/.env)
current_dir = os.path.dirname(os.path.abspath(__file__))
inner_env_path = os.path.join(current_dir, '..', '..', 'pharmaProject', '.env')
if os.path.exists(inner_env_path):
    load_dotenv(inner_env_path)

GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', default='')

def extract_prescription_data(image_file):
    """
    Sends the prescription image to Gemini API to extract details.
    image_file: file-like object or bytes
    """
    api_key = GEMINI_API_KEY

    if not api_key:
        raise ValueError("Gemini API key is not configured. Please set GEMINI_API_KEY in environment variables.")

    # Read image bytes
    if hasattr(image_file, 'read'):
        image_data = image_file.read()
    else:
        image_data = image_file

    base64_image = base64.b64encode(image_data).decode('utf-8')

    prompt = (
        "You are an expert pharmacist and medical AI. Parse this doctor's prescription image and extract the following details:\n"
        "1. Patient's name (if visible)\n"
        "2. Patient's phone (if visible)\n"
        "3. Doctor's name (if visible)\n"
        "4. List of medicines/drugs. For each medicine, extract:\n"
        "   - name: The clean brand name or generic name without qualifiers. Strip prefixes like 'Tab.', 'Tab', 'Cap.', 'Cap', 'Syr.', 'Syr', 'Oint.', 'Oint', 'Inj.', 'Inj', 'Adv:', 'Adv' (e.g., if prescription says 'Tab. Augmentin 625mg', name should be 'Augmentin' and strength/dosage should be '625mg'. If it says 'Syr. Alkalos', name should be 'Alkalos')\n"
        "   - dosage: Strength/dosage (e.g. '625mg', '40mg', 'SR 500mg', '100/10/1000')\n"
        "   - qty: Calculate the total quantity prescribed using standard medical guidelines:\n"
        "       a) Frequency: '1-0-1' or 'BD' = 2 per day. '1-1-1' or 'TDS' = 3 per day. '1-0-0' or 'OD' = 1 per day. '0-0-1' = 1 per day. '1-1-1-1' = 4 per day.\n"
        "       b) Duration: Multiply the frequency by the duration (e.g., '1-0-1 x 5 days' = 2 * 5 = 10 tablets. '1-0-0 x 5 days' = 1 * 5 = 5 tablets).\n"
        "       c) If the item is a Syrup, Ointment, Gel, Cream, Drops, Gum Paint, Spray, or Inhaler, set qty to 1 (representing 1 bottle/tube/pack) unless a specific larger count of bottles is written.\n"
        "       d) If duration is not specified, default to 10 for tablets/capsules and 1 for syrups/ointments.\n\n"
        "Output MUST be a valid JSON object matching this schema:\n"
        "{\n"
        "  \"patient_name\": \"string or null\",\n"
        "  \"patient_phone\": \"string or null\",\n"
        "  \"doctor_name\": \"string or null\",\n"
        "  \"medicines\": [\n"
        "    {\n"
        "      \"name\": \"string\",\n"
        "      \"dosage\": \"string\",\n"
        "      \"qty\": integer\n"
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
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        # If Gemini is busy (503) or rate-limited (429), retry after a short delay
        if response.status_code in [429, 503] and attempt < max_retries - 1:
            time.sleep(1.5)
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
