import psycopg2
import os

# Production DB URL
DB_URL = "postgresql://krew_db_user:WXMteDgjBiceQO2On6GRDOXow3ZWaAIE@dpg-d5pb8aer433s73d713jg-a.singapore-postgres.render.com/krew_db"

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
