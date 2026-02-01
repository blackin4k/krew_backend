import boto3
import psycopg2
import urllib3
import re
from pathlib import Path

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Config
DB_URL = "postgresql://krew_db_user:WXMteDgjBiceQO2On6GRDOXow3ZWaAIE@dpg-d5pb8aer433s73d713jg-a.singapore-postgres.render.com/krew_db"
R2_ENDPOINT_URL = "https://5e22fa30a7744b769bea5ad23240ed75.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "da67313054174317af24874313f88f00"
R2_SECRET_ACCESS_KEY = "80f1e7123aa24b22c7a40bce3f619e09968a35cc988fdcae6dec24d86891eb8f"
R2_BUCKET_NAME = "krew-music"

def sanitize_key(filename):
    name = Path(filename).stem
    ext = Path(filename).suffix
    clean_name = name.replace(" ", "_")
    clean_name = re.sub(r'[^a-zA-Z0-9._-]', '', clean_name)
    return f"{clean_name}{ext}"

def bulk_fix():
    print("🚀 Starting Bulk Cover Fix...")
    
    # 1. Connect to DB
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        print("✅ DB Connected.")
    except Exception as e:
        print(f"❌ DB Connection Failed: {e}")
        return

    # 2. List all covers in R2 (efficient lookup)
    print("📂 Scanning R2 covers (this might take a moment)...")
    r2_covers = set()
    try:
        session = boto3.session.Session()
        s3 = session.client(
            's3', 
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
            verify=False
        )
        paginator = s3.get_paginator('list_objects_v2')
        count = 0
        for page in paginator.paginate(Bucket=R2_BUCKET_NAME, Prefix='covers/'):
            if 'Contents' in page:
                for obj in page['Contents']:
                    r2_covers.add(obj['Key'])
                    count += 1
        print(f"✅ Indexed {count} covers from R2.")
    except Exception as e:
        print(f"❌ R2 Scan Failed: {e}")
        return

    # 3. Find Broken Songs
    cur.execute("SELECT id, title, audio_file FROM song WHERE cover_file IS NULL OR cover_file = 'None' OR cover_file = '';")
    broken_songs = cur.fetchall()
    print(f"🔍 Found {len(broken_songs)} songs with missing covers.")

    fixed_count = 0
    
    # 4. Fix Loop
    for song in broken_songs:
        sid, title, audio_file = song
        # audio_file might be "Song.mp3" or "audio/Song.mp3"
        # We need the stem "Song"
        base_name = Path(audio_file).stem 
        # But wait, audio_file might be sanitized already or not?
        # Check logs: DB has "Kaifi_Khalil..." (sanitized).
        
        # Candidate keys to check
        candidates = [
            f"covers/{base_name}_cover.jpg",
            f"covers/{base_name}_cover.png",
            f"covers/{base_name}_cover.jpeg",
            f"covers/{base_name}_cover.webp",
            f"covers/{base_name}.jpg",
            f"covers/{base_name}.png"
        ]
        
        found_key = None
        for cand in candidates:
            if cand in r2_covers:
                found_key = cand
                break
        
        if found_key:
            print(f"🛠️ Fixing '{title}': Found {found_key}")
            cur.execute("UPDATE song SET cover_file = %s WHERE id = %s;", (found_key, sid))
            fixed_count += 1
        else:
            print(f"⚠️ Could not find cover for '{title}' (Base: {base_name})")

    conn.commit()
    conn.close()
    print(f"\n🎉 Done! Fixed {fixed_count} songs.")

if __name__ == "__main__":
    bulk_fix()
