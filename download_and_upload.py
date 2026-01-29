
import os
import yt_dlp as ytdlp
import boto3
import glob

# R2 Configuration (Same as your project)
R2_ENDPOINT_URL = "https://ced7d2775d362f5eee444f2ec74bd7fd.r2.cloudflarestorage.com"
R2_ACCESS_KEY_ID = "0022f6249cf59fb8f55da24eea22cbd2"
R2_SECRET_ACCESS_KEY = "a8b8964edaa3693bd66bc35fd2296510c55260c17acab030b6ffdbe49b375c28"
R2_BUCKET_NAME = "krew-music"

def download_and_upload(youtube_url):
    print(f"⬇️ Downloading: {youtube_url}")
    
    # Configure yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [
            {'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'},
            {'key': 'FFmpegMetadata'}, # Adds artist, title, album
            {'key': 'EmbedThumbnail'}, # Adds cover art
        ],
        'writethumbnail': True,
        'outtmpl': 'downloaded_songs/%(artist)s - %(title)s.%(ext)s',
        'quiet': False,
        'no_warnings': True,
    }

    # Download
    with ytdlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(youtube_url, download=True)
        title = info_dict.get('title', 'Unknown')
        print(f"✅ Downloaded: {title}")

    # Find the downloaded MP3
    files = glob.glob("downloaded_songs/*.mp3")
    if not files:
        print("❌ Error: MP3 file not found after download.")
        return

    mp3_file = max(files, key=os.path.getctime) # Get most recent
    
    # Clean filename (remove [Official Video] etc if yt-dlp didn't)
    # The outtmpl above usually handles it, but safety first
    base_name = os.path.basename(mp3_file)
    base_name_no_ext = os.path.splitext(base_name)[0]
    
    # Find the matching cover (.jpg or .webp that yt-dlp downloaded)
    cover_file = None
    possible_covers = glob.glob(f"downloaded_songs/{base_name_no_ext}.*")
    for f in possible_covers:
        if f.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            cover_file = f
            break
            
    print(f"☁️ Uploading Audio: {base_name}...")
    
    # Upload to R2
    s3 = boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto"
    )

    try:
        # Upload Audio
        s3.upload_file(mp3_file, R2_BUCKET_NAME, f"audio/{base_name}")
        print(f"✅ Audio Uploaded: audio/{base_name}")
        
        # Upload Cover (if found)
        if cover_file:
            print(f"☁️ Uploading Cover: {os.path.basename(cover_file)}...")
            # Enforce .jpg extension for consistency in finding it later
            # (R2/S3 doesn't care about extension vs content-type, but our app matching logic does)
            target_cover_name = f"covers/{base_name_no_ext}.jpg"
            s3.upload_file(cover_file, R2_BUCKET_NAME, target_cover_name)
            print(f"✅ Cover Uploaded: {target_cover_name}")
        else:
            print("⚠️ No cover art found to upload.")

        print("🚀 Now check your app in ~5 minutes (the server needs to restart to auto-sync, or you can trigger a deploy).")
    except Exception as e:
        print(f"❌ Upload Failed: {e}")

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        url = sys.argv[1]
    else:
        url = input("Enter YouTube Music URL: ").strip()
        
    if url:
        download_and_upload(url)
