
import os
import sys
from sqlalchemy import create_engine, text

# Default to the URL from sync_to_render.py if not provided
# Note: Users should ideally provide this via Env Var, but we have it hardcoded in sync_to_render.py
# which implies it's semi-public or at least accessible to the dev.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://krew_db_user:WXMteDgjBiceQO2On6GRDOXow3ZWaAIE@dpg-d5pb8aer433s73d713jg-a.singapore-postgres.render.com/krew_db")

def migrate():
    print(f"🔌 Connecting to database...")
    if "postgres" not in DATABASE_URL and "sqlite" not in DATABASE_URL:
        print("❌ Invalid DATABASE_URL. Must be a postgres or sqlite connection string.")
        return

    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            print("🔍 Checking if 'lyrics' column exists...")
            
            # Check for PostgreSQL or SQLite
            try:
                # Try adding the column. If it exists, it will fail, which is fine.
                conn.execute(text("ALTER TABLE song ADD COLUMN lyrics TEXT"))
                conn.commit()
                print("✅ Success: Added 'lyrics' column to 'song' table.")
            except Exception as e:
                if "duplicate column" in str(e) or "already exists" in str(e):
                    print("ℹ️ Column 'lyrics' already exists. No changes made.")
                else:
                    print(f"❌ Error adding column: {e}")
                    
    except Exception as e:
        print(f"❌ Connection failed: {e}")

if __name__ == "__main__":
    migrate()
