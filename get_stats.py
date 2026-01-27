
import os
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta

# Production DB URL from render-krew-db.txt
DB_URL = "postgresql://krew_db_user:WXMteDgjBiceQO2On6GRDOXow3ZWaAIE@dpg-d5pb8aer433s73d713jg-a.singapore-postgres.render.com/krew_db"

def get_stats():
    try:
        engine = create_engine(DB_URL)
        with engine.connect() as conn:
            # 1. Total Users
            user_count = conn.execute(text("SELECT COUNT(*) FROM \"user\"")).scalar()
            
            # 2. Total Songs
            song_count = conn.execute(text("SELECT COUNT(*) FROM song")).scalar()
            
            # 3. Total Plays
            play_count = conn.execute(text("SELECT COUNT(*) FROM play_logs")).scalar()
            
            # 4. Active Users (last 7 days)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            active_users_7d = conn.execute(
                text("SELECT COUNT(DISTINCT user_id) FROM play_logs WHERE played_at > :d"),
                {"d": seven_days_ago}
            ).scalar()
            
            # 5. New Users (last 7 days)
            # Assuming we can check ArtistApplication or just user count growth if we had historical data
            # But we can just count users created if they have a created_at column.
            # Let's check User table columns first if possible, or just skip.
            
            print(f"--- KREW APP STATISTICS ---")
            print(f"Total Users: {user_count}")
            print(f"Total Songs: {song_count}")
            print(f"Total Plays: {play_count}")
            print(f"Active Users (Last 7 Days): {active_users_7d}")
            
    except Exception as e:
        print(f"Error fetching stats: {e}")

if __name__ == "__main__":
    get_stats()
