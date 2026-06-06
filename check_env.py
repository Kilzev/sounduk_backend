import os
from dotenv import load_dotenv

load_dotenv()

vars_to_check = [
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_REGION_NAME",
    "S3_BUCKET_NAME",
    "YOUTUBE_AUDIO_PROVIDER",
]

provider = (os.getenv("YOUTUBE_AUDIO_PROVIDER") or "ytdlp").strip().lower()
if provider == "rapidapi":
    vars_to_check.extend(["RAPIDAPI_KEY", "YOUTUBE_MP3_HOST", "YOUTUBE_MP3_PATH"])

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
