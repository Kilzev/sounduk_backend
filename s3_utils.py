
import boto3
import os
from dotenv import load_dotenv
import certifi

load_dotenv()

def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=os.getenv("S3_ENDPOINT_URL"),
        aws_access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
        region_name=os.getenv("S3_REGION_NAME"),
        verify=certifi.where()
    )

S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
