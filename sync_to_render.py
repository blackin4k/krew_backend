import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import os

# CONFIGURATION
LOCAL_DB = "instance/db.sqlite3"
# Using the External URL from your render-krew-db.txt
REMOTE_DB_URL = "postgresql://krew_db_user:WXMteDgjBiceQO2On6GRDOXow3ZWaAIE@dpg-d5pb8aer433s73d713jg-a.singapore-postgres.render.com/krew_db"

def sync_songs():
    print("Connecting to local database...")
    local_conn = sqlite3.connect(LOCAL_DB)
    local_cursor = local_conn.cursor()

    print("Connecting to remote Render database...")
    remote_conn = psycopg2.connect(REMOTE_DB_URL)
    remote_cursor = remote_conn.cursor()

    # 1. SYNC SONGS
    print("Syncing songs...")
    local_cursor.execute("SELECT id, title, artist, album, audio_file, cover_file, uploaded_by, genre, lyrics FROM song")
    songs = local_cursor.fetchall()
    print(f"Found {len(songs)} songs locally.")

    # Clear existing songs in remote (optional, but safer for clean sync)
    remote_cursor.execute("DELETE FROM song")
    
    insert_query = """
        INSERT INTO song (id, title, artist, album, audio_file, cover_file, uploaded_by, genre, lyrics)
        VALUES %s
    """
    execute_values(remote_cursor, insert_query, songs)
    print("✅ Songs synced!")

    # 2. SYNC ARTISTS
    print("Syncing artists...")
    local_cursor.execute("SELECT id, name, image_url, bio FROM artist")
    artists = local_cursor.fetchall()
    
    remote_cursor.execute("DELETE FROM artist")
    insert_artist_query = """
        INSERT INTO artist (id, name, image_url, bio)
        VALUES %s
    """
    execute_values(remote_cursor, insert_artist_query, artists)
    print("✅ Artists synced!")

    remote_conn.commit()
    
    local_conn.close()
    remote_conn.close()
    print("\n🎉 ALL DONE! Your Render database is now synced with your local library.")

if __name__ == "__main__":
    sync_songs()
