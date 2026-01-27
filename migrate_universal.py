
import os
from sqlalchemy import text
from app import app, db

def migrate():
    """
    Universal migration script that works for both SQLite (Local) and PostgreSQL (Render).
    It checks for missing columns and attempts to add them using standard SQL.
    """
    with app.app_context():
        db_url = app.config['SQLALCHEMY_DATABASE_URI']
        print(f"🔧 Checkig Database: {db_url.split('@')[-1] if '@' in db_url else db_url} ...")
        
        # Helper to check and add column
        def ensure_column(table, column, col_type):
            try:
                # Try to select the column to see if it exists
                db.session.execute(text(f"SELECT {column} FROM {table} LIMIT 1"))
                print(f"✅ '{column}' exists in '{table}'.")
            except Exception:
                print(f"⚠️ '{column}' missing in '{table}'. Adding...")
                db.session.rollback() # Reset transaction after error
                try:
                    # ALTER TABLE syntax is generally compatible for basic types
                    db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                    db.session.commit()
                    print(f"🎉 Successfully added '{column}'.")
                except Exception as e:
                    db.session.rollback()
                    print(f"❌ Failed to add '{column}': {e}")

        # --- 1. SONG TABLE ---
        print("\nChecking 'song' table...")
        ensure_column("song", "lyrics", "TEXT")

        # --- 2. USER TABLE ---
        print("\nChecking 'user' table...")
        # Note: 'BOOLEAN' works in PG, maps to INTEGER in SQLite usually fine via SQLAlchemy, 
        # but raw SQL might need care. For 'ALTER TABLE' adding a column, most DBs accept it.
        # SQLite uses INTEGER/NUMERIC for boolean but usually accepts the word BOOLEAN in DDL.
        # Postgres definitely accepts BOOLEAN.
        ensure_column("user", "is_artist", "BOOLEAN DEFAULT FALSE")
        
        # Postgres 'TIMESTAMP' is standard. SQLite accepts it as affinity.
        ensure_column("user", "artist_application_date", "TIMESTAMP")
        ensure_column("user", "artist_bio", "TEXT")

        print("\n✨ Migration checks complete.")

if __name__ == "__main__":
    migrate()
