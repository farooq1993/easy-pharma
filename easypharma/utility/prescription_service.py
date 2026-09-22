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

GEMINI_API_KEY = get_gemini_api_key = get_gemini_api_keys

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

def extract_prescription_data(image_file):
    """
    Sends the prescription image to AI Vision API to extract details.
    image_file: file-like object or bytes
    """
    api_key = get_gemini_api_key() or GEMINI_API_KEY
    if api_key:
        api_key = api_key.split('#')[0].strip().strip('"').strip("'").split()[0]

    if not api_key:
        logger.error("AI API key is missing in environment variables.")
        raise ValueError("AI Prescription Scanner is not configured. Please contact administrator.")

    base64_image = _prepare_and_optimize_image(image_file)

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
        "Return ONLY the raw JSON block without markdown formatting or code blocks."
    )

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

    api_keys = get_gemini_api_keys()
    if not api_keys:
        logger.error("AI API key is missing in environment variables.")
        raise ValueError("AI Prescription Scanner is not configured. Please contact administrator.")

    last_error = None
    response = None
    timeout = 45

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
                        sleep_time = (1.5 * (attempt + 1)) + random.uniform(0.3, 0.8)
                        last_error = f"Key #{key_idx+1} {model_name} status 503 (High Demand). Retrying in {sleep_time:.2f}s..."
                        logger.warning(last_error)
                        time.sleep(sleep_time)
                    elif res.status_code == 429:
                        last_error = f"Key #{key_idx+1} {model_name} status 429 (Quota exceeded)"
                        logger.warning(last_error)
                        break
                    elif res.status_code == 404:
                        last_error = f"Key #{key_idx+1} {model_name} status 404 (Not Found)"
                        break
                    else:
                        last_error = f"Key #{key_idx+1} {model_name} status {res.status_code}: {res.text[:150]}"
                        logger.warning(f"Prescription OCR attempt error: {last_error}")
                        break
                except requests.exceptions.Timeout:
                    last_error = f"Key #{key_idx+1} {model_name} timed out after {timeout}s"
                    logger.warning(last_error)
                    break
                except Exception as e:
                    last_error = f"Key #{key_idx+1} {model_name} exception: {str(e)}"
                    logger.warning(f"Prescription OCR request exception: {last_error}")
                    break

            if response and response.status_code == 200:
                break
        if response and response.status_code == 200:
            break

    if not response or response.status_code != 200:
        logger.error(f"Prescription OCR failed across all keys and models. Last details: {last_error}")
        raise Exception("AI Prescription Scanner is currently busy or unable to process this document. Please ensure the image is clear and try again.")

    resp_json = response.json()
    try:
        raw_text = resp_json['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError):
        logger.error(f"Invalid AI response structure for prescription: {resp_json}")
        raise Exception("Unable to parse prescription details. Please ensure the image is clear.")

    # Parse and clean JSON
    cleaned_text = raw_text.strip()
    match = re.search(r'```(?:json)?\s*(.*?)\s*```', cleaned_text, re.DOTALL)
    if match:
        cleaned_text = match.group(1)
    
    try:
        parsed_data = json.loads(cleaned_text.strip())
        return parsed_data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse prescription output as JSON: {cleaned_text}. Error: {e}")
        raise Exception("Could not extract structured prescription details from this image.")
