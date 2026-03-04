import boto3
import os
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_REGION_NAME = os.getenv("S3_REGION_NAME")
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY")

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=S3_ENDPOINT_URL,
        region_name=S3_REGION_NAME,
        aws_access_key_id=S3_ACCESS_KEY_ID,
        aws_secret_access_key=S3_SECRET_ACCESS_KEY
    )

def generate_presigned_url(object_name, expiration=3600):
    s3_client = get_s3_client()
    try:
        response = s3_client.generate_presigned_url('get_object',
                                                    Params={'Bucket': S3_BUCKET_NAME,
                                                            'Key': object_name},
                                                    ExpiresIn=expiration)
    except Exception as e:
        print(f"Error generating presigned URL: {e}")
        return None
    return response

def upload_file_to_s3(file_obj, object_name):
    s3_client = get_s3_client()
    try:
        s3_client.upload_fileobj(file_obj, S3_BUCKET_NAME, object_name)
    except Exception as e:
        print(f"Error uploading file to S3: {e}")
        return False
    return True

def delete_file_from_s3(object_name):
    s3_client = get_s3_client()
    try:
        s3_client.delete_object(Bucket=S3_BUCKET_NAME, Key=object_name)
    except Exception as e:
        print(f"Error deleting file from S3: {e}")
        return False
    return True
