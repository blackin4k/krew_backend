import boto3
import os

# R2 Config (Manual for script)
R2_ENDPOINT_URL = "https://5e22fa30a7744b769bea5ad23240ed75.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "da67313054174317af24874313f88f00"
R2_SECRET_ACCESS_KEY = "80f1e7123aa24b22c7a40bce3f619e09968a35cc988fdcae6dec24d86891eb8f"
R2_BUCKET_NAME = "krew-music"

import sys
import certifi
import ssl
import requests

def find_cover():
    print(f"SSL Version: {ssl.OPENSSL_VERSION}")
    try:
        print("Test: Connecting to google.com...")
        requests.get("https://google.com", timeout=5)
        print("✅ Google connection successful")
    except Exception as e:
        print(f"❌ Google connection failed: {e}")

    query = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if not query:
        print("Usage: python find_cover.py <search_term>")
        return

    try:
        s3 = boto3.client(
            's3',
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
            verify=False
        )
        
        print(f"🔍 Searching for '{query}' covers in R2...")
        paginator = s3.get_paginator('list_objects_v2')
        found = False
        
        for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix='covers/'):
            if 'Contents' in page:
                for obj in page['Contents']:
                    if query in obj['Key'].lower():
                        print(f"✅ Found: {obj['Key']}")
                        found = True
        
        if not found:
            print(f"❌ No matching cover found for '{query}' in R2.")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    find_cover()
