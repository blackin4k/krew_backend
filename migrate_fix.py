
import sqlite3
import os

# Path to database
db_path = os.path.join(os.getcwd(), 'instance', 'db.sqlite3')
print(f"Checking database at: {db_path}")

if not os.path.exists(db_path):
    print("❌ Database file not found!")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# 1. Get current columns
cursor.execute("PRAGMA table_info(play_logs)")
columns = [row[1] for row in cursor.fetchall()]
print(f"Current columns in play_logs: {columns}")

# 2. Add 'listen_duration' if missing
if 'listen_duration' not in columns:
    print("⚠️ 'listen_duration' missing. Adding...")
    try:
        cursor.execute("ALTER TABLE play_logs ADD COLUMN listen_duration INTEGER DEFAULT 0")
        print("✅ Added 'listen_duration'")
    except Exception as e:
        print(f"❌ Failed to add 'listen_duration': {e}")
else:
    print("✅ 'listen_duration' exists.")

# 3. Add 'completed' if missing
if 'completed' not in columns:
    print("⚠️ 'completed' missing. Adding...")
    try:
        cursor.execute("ALTER TABLE play_logs ADD COLUMN completed BOOLEAN DEFAULT 0")
        print("✅ Added 'completed'")
    except Exception as e:
        print(f"❌ Failed to add 'completed': {e}")
else:
    print("✅ 'completed' exists.")

conn.commit()
conn.close()
print("Migration check complete.")
