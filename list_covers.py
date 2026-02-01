import boto3
import os
import urllib3

# Disable SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Config
R2_ENDPOINT_URL = "https://5e22fa30a7744b769bea5ad23240ed75.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "da67313054174317af24874313f88f00"
R2_SECRET_ACCESS_KEY = "80f1e7123aa24b22c7a40bce3f619e09968a35cc988fdcae6dec24d86891eb8f"
R2_BUCKET_NAME = "krew-music"

def list_all_covers():
    try:
        session = boto3.session.Session()
        s3 = session.client(
            's3',
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
            verify=False # Disable SSL verify
        )
        
        print("📂 Listing all files in 'covers/'...")
        paginator = s3.get_paginator('list_objects_v2')
        
        found_kahani = False
        count = 0
        
        for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix='covers/'):
            if 'Contents' in page:
                for obj in page['Contents']:
                    key = obj['Key']
                    count += 1
                    # print(key) # Too noisy to print all
                    if 'kahani' in key.lower():
                        print(f"🎯 FOUND MATCH: {key}")
                        found_kahani = True
        
        print(f"Total covers scanned: {count}")
        if not found_kahani:
            print("❌ No cover with 'kahani' in filename found.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    list_all_covers()
