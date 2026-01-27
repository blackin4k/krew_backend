
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
cursor.execute("PRAGMA table_info(user)")
columns = [row[1] for row in cursor.fetchall()]
print(f"Current columns in user: {columns}")

# 2. Add 'is_artist' if missing
if 'is_artist' not in columns:
    print("⚠️ 'is_artist' missing. Adding...")
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN is_artist BOOLEAN DEFAULT 0")
        print("✅ Added 'is_artist'")
    except Exception as e:
        print(f"❌ Failed to add 'is_artist': {e}")
else:
    print("✅ 'is_artist' column already exists.")

# 3. Add 'artist_application_date' if missing
if 'artist_application_date' not in columns:
    print("⚠️ 'artist_application_date' missing. Adding...")
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN artist_application_date TIMESTAMP")
        print("✅ Added 'artist_application_date'")
    except Exception as e:
        print(f"❌ Failed to add 'artist_application_date': {e}")
else:
    print("✅ 'artist_application_date' column already exists.")

# 4. Add 'artist_bio' if missing
if 'artist_bio' not in columns:
    print("⚠️ 'artist_bio' missing. Adding...")
    try:
        cursor.execute("ALTER TABLE user ADD COLUMN artist_bio TEXT")
        print("✅ Added 'artist_bio'")
    except Exception as e:
        print(f"❌ Failed to add 'artist_bio': {e}")
else:
    print("✅ 'artist_bio' column already exists.")

conn.commit()
conn.close()
print("Migration check complete.")
