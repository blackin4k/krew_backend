import psycopg2
import os

# Production DB URL from User
DB_URL = "postgresql://postgres.jizmyglvxuczdfxfkmul:falakdarealart@aws-1-ap-northeast-1.pooler.supabase.com:5432/postgres"

def check_stats():
    try:
        print(f"Connecting to database...")
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Check most played songs
        print("\n--- 🎵 Most Played Songs ---")
        query = """
        SELECT s.title, s.artist, COUNT(p.id) as play_count
        FROM song s
        JOIN play_logs p ON s.id = p.song_id
        GROUP BY s.id, s.title, s.artist
        ORDER BY play_count DESC
        LIMIT 10;
        """
        
        try:
            cur.execute(query)
            rows = cur.fetchall()
            if not rows:
                print("No plays recorded yet.")
            for i, row in enumerate(rows, 1):
                # row = (Title, Artist, Count)
                print(f"{i}. {row[0]} - {row[1]} ({row[2]} plays)")
        except psycopg2.Error as e:
            print(f"Query Error (checking tables instead): {e}")
            conn.rollback()
            # If table name is wrong, list tables
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';")
            tables = cur.fetchall()
            print("Available tables:", [t[0] for t in tables])

        print("\n--- 📊 Total Stats ---")
        try:
            cur.execute("SELECT COUNT(*) FROM song;")
            song_count = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM user;")
            user_count = cur.fetchone()[0] # 'user' might be reserved keyword in some SQL, but usually fine in postgres if quoted or logic context. Flask-SQLAlchemy usually assumes 'user' table for User model.
            print(f"Total Songs: {song_count}")
            print(f"Total Users: {user_count}")
        except:
             # retry for user table with quotes if needed
             conn.rollback()
             cur.execute('SELECT COUNT(*) FROM "user";')
             user_count = cur.fetchone()[0]
             print(f"Total Users: {user_count}")

        conn.close()

    except Exception as e:
        print(f"\n❌ Connection Failed: {e}")

if __name__ == "__main__":
    check_stats()
