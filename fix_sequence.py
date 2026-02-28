
import psycopg2
import os

# Render Database URL (Hardcoded for your convenience based on previous context)
# If this changed, please update it.
DATABASE_URL = "postgresql://postgres.jizmyglvxuczdfxfkmul:falakdarealart@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"

def fix_sequence():
    print("🔌 Connecting to Render Database...")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cursor = conn.cursor()
        
        print("🔧 Checking Song ID Sequence...")
        
        # 1. Get the current Max ID
        cursor.execute("SELECT MAX(id) FROM song;")
        max_id = cursor.fetchone()[0]
        
        if max_id is None:
            max_id = 0
            print("   -> No songs found (Max ID = 0)")
        else:
            print(f"   -> Current Max ID in table: {max_id}")

        # 2. Reset sequence to Max ID + 1
        # The sequence name is usually table_column_seq. For 'song' table 'id' column: 'song_id_seq'
        seq_name = 'song_id_seq'
        
        print(f"🔄 Resetting sequence '{seq_name}' to {max_id + 1}...")
        cursor.execute(f"SELECT setval('{seq_name}', %s);", (max_id + 1,))
        
        conn.commit()
        print("✅ Message: Sequence fixed! New songs can now be inserted.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    fix_sequence()
