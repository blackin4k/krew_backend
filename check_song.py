
import psycopg2
import sys

# Render Database URL
DATABASE_URL = "postgresql://krew_db_user:WXMteDgjBiceQO2On6GRDOXow3ZWaAIE@dpg-d5pb8aer433s73d713jg-a.singapore-postgres.render.com/krew_db"

def check_song(filename_fragment):
    print(f"🔍 Searching for songs containing '{filename_fragment}' in Render DB...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        query = "SELECT id, title, audio_file FROM song WHERE audio_file ILIKE %s;"
        cursor.execute(query, (f"%{filename_fragment}%",))
        
        rows = cursor.fetchall()
        
        if rows:
            print(f"✅ Found {len(rows)} match(es):")
            for row in rows:
                print(f"   - ID: {row[0]} | Title: {row[1]} | File: {row[2]}")
        else:
            print("❌ No matches found.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    check_song("The Winner Takes It All")
