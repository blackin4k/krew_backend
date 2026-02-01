import boto3
import urllib3
from botocore.exceptions import ClientError

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

R2_ENDPOINT_URL = "https://5e22fa30a7744b769bea5ad23240ed75.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "da67313054174317af24874313f88f00"
R2_SECRET_ACCESS_KEY = "80f1e7123aa24b22c7a40bce3f619e09968a35cc988fdcae6dec24d86891eb8f"
R2_BUCKET_NAME = "krew-music"

def check_keys():
    session = boto3.session.Session()
    s3 = session.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        verify=False
    )

    keys_to_check = [
        "covers/Kaifi_Khalil_Ario_-_Kahani_Suno_2.O.jpg",
        "covers/Kaifi_Khalil_Ario_-_Kahani_Suno_2.O.png",
        "covers/Kaifi_Khalil_Ario_-_Kahani_Suno_2.O.jpeg",
        "covers/Kahani_Suno_2.O.jpg",
        "Kaifi_Khalil_Ario_-_Kahani_Suno_2.O.jpg"
    ]
    
    print("🔍 Checking keys in R2...")
    for key in keys_to_check:
        try:
            s3.head_object(Bucket=R2_BUCKET_NAME, Key=key)
            print(f"✅ FOUND: {key}")
        except ClientError as e:
            if e.response['Error']['Code'] == "404":
                print(f"❌ Not Found: {key}")
            else:
                print(f"⚠️ Error checking {key}: {e}")

if __name__ == "__main__":
    check_keys()
