from yookassa import Configuration, Payment
import os
import uuid
import json
from dotenv import load_dotenv

# Load env from the project directory
load_dotenv()

shop_id = os.getenv("YOOKASSA_SHOP_ID")
secret_key = os.getenv("YOOKASSA_SECRET_KEY")

print(f"DEBUG: Shop ID loaded: {shop_id}")
# Mask secret key for logs
masked_key = secret_key[:4] + "***" + secret_key[-4:] if secret_key and len(secret_key) > 8 else "None"
print(f"DEBUG: Secret Key loaded: {masked_key}")

Configuration.account_id = shop_id
Configuration.secret_key = secret_key

try:
    payment = Payment.create({
        "amount": {
            "value": "100.00",
            "currency": "RUB"
        },
        "confirmation": {
            "type": "redirect",
            "return_url": "https://www.example.com/return_url"
        },
        "capture": True,
        "description": "Test payment check"
    }, uuid.uuid4())

    print(f"✅ Payment created successfully!")
    print(f"Payment ID: {payment.id}")
    print(f"Confirmation URL: {payment.confirmation.confirmation_url}")

except Exception as e:
    print(f"❌ Error creating payment: {e}")
