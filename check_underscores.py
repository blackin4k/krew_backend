from app import app, db, Song
from sqlalchemy import text

def check_underscores():
    with app.app_context():
        print("🔍 Scanning database for songs with underscores in Title or Artist...")
        
        # SQL Query to find literal underscores (escaped with backslash)
        # Note: In standard SQL, you often need "LIKE '%\_%' ESCAPE '\'"
        # But Postgres usually accepts '%\_%' by default if standard_conforming_strings is on.
        sql = text(r"SELECT id, title, artist FROM song WHERE title LIKE '%\_%' OR artist LIKE '%\_%'")
        
        results = db.session.execute(sql).fetchall()
        
        if not results:
            print("✅ No songs found with underscores.")
            return

        print(f"⚠️ Found {len(results)} songs with underscores:")
        print("-" * 50)
        for row in results:
            print(f"ID: {row.id}")
            print(f"   Artist: {row.artist}")
            print(f"   Title:  {row.title}")
            print("-" * 50)

if __name__ == "__main__":
    check_underscores()
