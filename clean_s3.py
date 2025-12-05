from s3_utils import get_s3_client, S3_BUCKET_NAME
import boto3

def clean_bucket():
    print(f"⚠️ WARNING: This will DELETE ALL DATA in bucket '{S3_BUCKET_NAME}'")
    confirm = input("Type 'DELETE' to confirm: ")
    
    if confirm != "DELETE":
        print("Operation cancelled.")
        return

    s3 = get_s3_client()
    
    try:
        # List all objects
        response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME)
        
        if 'Contents' not in response:
            print("Bucket is already empty.")
            return

        objects = [{'Key': obj['Key']} for obj in response['Contents']]
        
        # Delete objects
        print(f"Deleting {len(objects)} objects...")
        s3.delete_objects(
            Bucket=S3_BUCKET_NAME,
            Delete={'Objects': objects}
        )
        print("✅ Bucket cleaned successfully!")
        
    except Exception as e:
        print(f"❌ Error cleaning bucket: {e}")

if __name__ == "__main__":
    clean_bucket()
