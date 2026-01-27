
import sqlite3
import os

# Path to database
db_path = os.path.join(os.getcwd(), 'instance', 'db.sqlite3')
print(f"Checking database at: {db_path}")

if not os.path.exists(db_path):
    print("❌ Database file not found at expected path. Trying one level up...")
    # Fallback for different CWD
    db_path = os.path.join(os.path.dirname(__file__), 'instance', 'db.sqlite3')

if not os.path.exists(db_path):
    print(f"❌ Database file still not found at {db_path}!")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Get current columns
cursor.execute("PRAGMA table_info(song)")
columns = [row[1] for row in cursor.fetchall()]
print(f"Current columns in song: {columns}")

# 2. Add 'lyrics' if missing
if 'lyrics' not in columns:
    print("⚠️ 'lyrics' missing. Adding...")
    try:
        cursor.execute("ALTER TABLE song ADD COLUMN lyrics TEXT")
        print("✅ Added 'lyrics'")
    except Exception as e:
        print(f"❌ Failed to add 'lyrics': {e}")
else:
    print("✅ 'lyrics' column already exists.")

conn.commit()
conn.close()
print("Migration check complete.")
