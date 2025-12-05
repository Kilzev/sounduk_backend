from s3_utils import get_s3_client, S3_BUCKET_NAME
import boto3

def test_connection():
    print(f"Testing connection to bucket: {S3_BUCKET_NAME}")
    try:
        s3 = get_s3_client()
        # Пытаемся получить список объектов (легкая операция)
        response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, MaxKeys=1)
        print("✅ S3 Connection successful!")
        if 'Contents' in response:
            print(f"Found object: {response['Contents'][0]['Key']}")
        else:
            print("Bucket is accessible but empty.")
    except Exception as e:
        print(f"❌ S3 Connection failed: {e}")

if __name__ == "__main__":
    test_connection()
