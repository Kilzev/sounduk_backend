import os
from dotenv import load_dotenv

load_dotenv()

vars_to_check = [
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_REGION_NAME",
    "S3_BUCKET_NAME"
]

print("Checking environment variables...")
for var in vars_to_check:
    value = os.getenv(var)
    if value is None:
        print(f"❌ MISSING: {var}")
    elif value == "":
        print(f"⚠️ EMPTY: {var}")
    else:
        # Показываем только первые 3 символа для безопасности
        masked = value[:3] + "***" if len(value) > 3 else "***"
        print(f"✅ OK: {var} = {masked}")
