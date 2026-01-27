import sqlite3
import os

# Connect to the SQLite database
# Adjust path if necessary based on where you run this script
db_path = os.path.join(os.path.dirname(__file__), 'instance', 'db.sqlite3')

if not os.path.exists(db_path):
    print(f"Error: Database not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Query for songs with artist 'Unknown'
    cursor.execute("SELECT title, audio_file FROM song WHERE artist = 'Unknown'")
    songs = cursor.fetchall()
    
    count = len(songs)
    print(f"Total songs with 'Unknown' artist: {count}")
    
    if count > 0:
        print("\nSong Titles:")
        for song in songs:
            print(f"- {song[0]} (File: {song[1]})")
            
except Exception as e:
    print(f"An error occurred: {e}")
finally:
    conn.close()
