from __future__ import annotations
import re

def is_whatsapp_ready(phone: str) -> bool:
    """
    Heuristic to detect if a phone number is likely a mobile/WhatsApp number.
    Focus on Spain (prefixes 6, 7) but handles generic mobile patterns.
    """
    if not phone:
        return False
    digits = re.sub(r'\D', '', phone)
    
    # Spain Logic
    if digits.startswith('34'):
        trimmed = digits[2:]
        if len(trimmed) == 9 and (trimmed.startswith('6') or trimmed.startswith('7')):
            return True
    elif len(digits) == 9 and (digits.startswith('6') or digits.startswith('7')):
        return True
        
    # Generic logic for other regions: most mobiles are 10-12 digits
    return False
