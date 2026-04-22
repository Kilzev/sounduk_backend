from yookassa import Configuration, Payment
import os
import sys
from dotenv import load_dotenv

# Load env from the project directory
load_dotenv()

shop_id = os.getenv("YOOKASSA_SHOP_ID")
secret_key = os.getenv("YOOKASSA_SECRET_KEY")

Configuration.account_id = shop_id
Configuration.secret_key = secret_key

# Payment ID from the previous run
payment_id = "313a2211-000f-5001-8000-10621cf03836"

try:
    payment = Payment.find_one(payment_id)
    print(f"Payment ID: {payment.id}")
    print(f"Status: {payment.status}")
    print(f"Paid: {payment.paid}")

    if payment.cancellation_details:
        print(f"Cancellation reason: {payment.cancellation_details.reason}")
        print(f"Cancellation party: {payment.cancellation_details.party}")

except Exception as e:
    print(f"❌ Error checking payment: {e}")
