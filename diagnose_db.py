
from app import app, db, PlayLog, Song, User
from datetime import datetime
import traceback

def test_db_insert():
    with app.app_context():
        print("🔍 Starting DB Diagnostic...")
        
        # 1. Fetch dependencies
        user = User.query.first()
        song = Song.query.first()
        
        if not user or not song:
            print("❌ Cannot test: Missing User or Song in DB")
            return

        print(f"👤 User: {user.id}")
        print(f"🎵 Song: {song.id}")

        # 2. Try Insert
        try:
            print("Attempting PlayLog insert...")
            log = PlayLog(
                user_id=user.id,
                song_id=song.id,
                played_at=datetime.utcnow(),
                completed=True,
                listen_duration=0
            )
            db.session.add(log)
            db.session.commit()
            print("✅ DB Insert SUCCESS! The Model/Schema is fine.")
        except Exception:
            print("❌ DB Insert FAILED!")
            traceback.print_exc()

if __name__ == "__main__":
    test_db_insert()
