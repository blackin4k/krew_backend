import psycopg2
import os

# Production DB URL
DB_URL = "postgresql://postgres.jizmyglvxuczdfxfkmul:falakdarealart@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"

def check_song_cover():
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        print("\n--- 🔍 Checking Song Metadata ---")
        cur.execute("SELECT id, title, cover_file, audio_file FROM song WHERE title ILIKE '%Kahani%';")
        rows = cur.fetchall()
        
        if not rows:
            print("❌ Song 'Kahani Suno 2.O' not found in DB.")
        else:
            for row in rows:
                print(f"ID: {row[0]}")
                print(f"Title: {row[1]}")
                print(f"Cover File (DB): '{row[2]}'")
                print(f"Audio File (DB): '{row[3]}'")
                
        conn.close()

    except Exception as e:
        print(f"❌ DB Check Failed: {e}")

if __name__ == "__main__":
    check_song_cover()
