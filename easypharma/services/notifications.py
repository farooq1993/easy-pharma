import requests
import logging
from django.conf import settings

logger = logging.getLogger('easypharma.notifications')

def send_whatsapp_message(phone, message, tenant=None):
    """
    Sends WhatsApp message via the configured gateway (UltraMsg, Twilio, or Mock).
    Returns (success: bool, error_msg: str)
    """
    if not phone:
        return False, "Phone number is empty"

    # Normalize phone number (strip whitespace and symbols)
    phone = "".join(filter(str.isdigit, str(phone)))

    # Auto prefix 91 if it's a 10 digit Indian number
    if len(phone) == 10:
        phone = "91" + phone

    # Retrieve gateway configuration from settings (with defaults)
    gateway = getattr(settings, 'WHATSAPP_GATEWAY_PROVIDER', 'mock').lower()

    if gateway == 'mock':
        logger.info(f"--- MOCK WHATSAPP MESSAGE SENT ---")
        logger.info(f"To: +{phone}")
        logger.info(f"Message:\n{message}")
        logger.info(f"---------------------------------")
        return True, ""

    elif gateway == 'ultramsg':
        instance_id = getattr(settings, 'ULTRAMSG_INSTANCE_ID', '')
        token = getattr(settings, 'ULTRAMSG_TOKEN', '')
        if not (instance_id and token):
            return False, "UltraMsg instance ID or token is missing in settings"

        url = f"https://api.ultramsg.com/{instance_id}/messages/chat"
        payload = {
            "token": token,
            "to": f"+{phone}" if not phone.startswith('+') else phone,
            "body": message,
            "priority": 10
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            res_data = response.json()
            if res_data.get('sent') == 'true' or 'id' in res_data:
                return True, ""
            return False, res_data.get('error', 'Unknown UltraMsg error response')
        except Exception as e:
            logger.error(f"UltraMsg API Error: {e}")
            return False, f"UltraMsg API Exception: {e}"

    elif gateway == 'twilio':
        account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
        auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
        from_whatsapp = getattr(settings, 'TWILIO_FROM_WHATSAPP', '') # e.g. 'whatsapp:+14155238886'

        if not (account_sid and auth_token and from_whatsapp):
            return False, "Twilio configuration (Account SID, Auth Token, or From Number) is missing in settings"

        # Formulate authorization header
        from requests.auth import HTTPBasicAuth
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        
        # Twilio WhatsApp requires numbers to be prefixed with 'whatsapp:'
        to_number = f"whatsapp:+{phone}"
        from_number = from_whatsapp if from_whatsapp.startswith('whatsapp:') else f"whatsapp:{from_whatsapp}"

        payload = {
            "To": to_number,
            "From": from_number,
            "Body": message
        }

        try:
            response = requests.post(url, data=payload, auth=HTTPBasicAuth(account_sid, auth_token), timeout=10)
            if response.status_code in [200, 201]:
                return True, ""
            res_data = response.json()
            return False, res_data.get('message', f"Twilio returned status code {response.status_code}")
        except Exception as e:
            logger.error(f"Twilio API Error: {e}")
            return False, f"Twilio API Exception: {e}"

    elif gateway == 'local_gateway':
        url = "http://localhost:8001/send-message"
        payload = {
            "phone": phone,
            "message": message
        }
        try:
            response = requests.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                res_data = response.json()
                if res_data.get('success'):
                    return True, ""
                return False, res_data.get('error', 'Unknown gateway error')
            else:
                try:
                    res_data = response.json()
                    return False, res_data.get('error', f"Gateway returned HTTP {response.status_code}")
                except:
                    return False, f"Gateway returned HTTP {response.status_code}"
        except Exception as e:
            logger.error(f"Local WhatsApp Gateway Error: {e}")
            return False, f"Could not connect to Local Gateway on port 8001: {e}"

    return False, f"Unsupported WhatsApp Gateway Provider: {gateway}"
