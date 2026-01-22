
from app import app, db
from sqlalchemy import text
import sys

print("Starting migration...")
try:
    with app.app_context():
        # Check if column exists first to avoid error spam? 
        # Actually easier to just catch exception.
        try:
            db.session.execute(text("ALTER TABLE playback_state ADD COLUMN history TEXT DEFAULT '[]'"))
            db.session.commit()
            print("SUCCESS: Added history column.")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                print("INFO: Column history already exists.")
            else:
                print(f"ERROR: Migration failed: {e}")
                sys.exit(1)
except Exception as e:
    print(f"CRITICAL: App context failed: {e}")
    sys.exit(1)
