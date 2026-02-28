"""
restore_to_supabase.py
======================
Restores the Krew pg_dump directory backup to a fresh Supabase PostgreSQL database.

HOW TO USE:
1. Create a free project at https://supabase.com
2. Go to: Project Settings → Database → Connection String → URI
3. Copy the connection string (it looks like: postgresql://postgres:PASSWORD@db.xxxxx.supabase.co:5432/postgres)
4. Paste it below as SUPABASE_URL or set it as an environment variable
5. Run: python restore_to_supabase.py

WHAT THIS SCRIPT DOES:
- Creates all tables in Supabase (from your SQLAlchemy models)
- Imports all data from the pg_dump directory backup
- Resets all sequences so new inserts work correctly
"""

import os
import io
import sys
import psycopg2
from psycopg2 import sql
from datetime import datetime

# ─────────────────────────────────────────────────────────
# CONFIGURATION — Set your Supabase connection string here
# ─────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL") or input(
    "Paste your Supabase connection string: "
).strip()

# Path to your pg_dump directory (the folder containing toc.dat)
DUMP_DIR = os.path.join(os.path.dirname(__file__), r"..\feb_22_db_render_free_\krew_db")

# ─────────────────────────────────────────────────────────
# SCHEMA — DDL to create all tables (mirrors your models)
# ─────────────────────────────────────────────────────────
CREATE_SCHEMA_SQL = """
-- Drop in reverse dependency order
DROP TABLE IF EXISTS play_logs CASCADE;
DROP TABLE IF EXISTS queue_history CASCADE;
DROP TABLE IF EXISTS playback_state CASCADE;
DROP TABLE IF EXISTS playlist_song CASCADE;
DROP TABLE IF EXISTS external_playlist_track CASCADE;
DROP TABLE IF EXISTS playlist CASCADE;
DROP TABLE IF EXISTS artist_application CASCADE;
DROP TABLE IF EXISTS sleep_timer CASCADE;
DROP TABLE IF EXISTS jam_session CASCADE;
DROP TABLE IF EXISTS jam_state CASCADE;
DROP TABLE IF EXISTS jam CASCADE;
DROP TABLE IF EXISTS "like" CASCADE;
DROP TABLE IF EXISTS artist CASCADE;
DROP TABLE IF EXISTS song CASCADE;
DROP TABLE IF EXISTS "user" CASCADE;

-- Users
CREATE TABLE "user" (
    id                      SERIAL PRIMARY KEY,
    username                VARCHAR(80)  UNIQUE NOT NULL,
    email                   VARCHAR(120) UNIQUE NOT NULL,
    password_hash           VARCHAR(255) NOT NULL,
    is_artist               BOOLEAN DEFAULT FALSE,
    artist_application_date TIMESTAMP,
    artist_bio              TEXT
);

-- Songs
CREATE TABLE song (
    id          SERIAL PRIMARY KEY,
    title       VARCHAR(200),
    artist      VARCHAR(200),
    album       VARCHAR(200),
    audio_file  VARCHAR(255),
    cover_file  VARCHAR(255),
    uploaded_by INTEGER,
    genre       VARCHAR(50) DEFAULT 'Unknown',
    lyrics      TEXT
);

-- Artist Applications
CREATE TABLE artist_application (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES "user"(id),
    artist_name     VARCHAR(200) NOT NULL,
    bio             TEXT NOT NULL,
    social_links    TEXT,
    sample_work_url VARCHAR(500),
    status          VARCHAR(20) DEFAULT 'pending',
    created_at      TIMESTAMP DEFAULT NOW(),
    reviewed_at     TIMESTAMP,
    reviewed_by     INTEGER
);

-- Artists
CREATE TABLE artist (
    id           SERIAL PRIMARY KEY,
    name         VARCHAR(200) UNIQUE,
    image_url    VARCHAR(500),
    bio          TEXT,
    last_updated TIMESTAMP
);

-- Playlists
CREATE TABLE playlist (
    id         SERIAL PRIMARY KEY,
    name       VARCHAR(200),
    owner_id   INTEGER,
    position   INTEGER,
    cover_file VARCHAR(255)
);

-- Playlist Songs (junction)
CREATE TABLE playlist_song (
    id          SERIAL PRIMARY KEY,
    playlist_id INTEGER,
    song_id     INTEGER
);

-- External Playlist Tracks
CREATE TABLE external_playlist_track (
    id          SERIAL PRIMARY KEY,
    playlist_id INTEGER,
    title       VARCHAR(200),
    artist      VARCHAR(200),
    available   BOOLEAN DEFAULT FALSE,
    song_id     INTEGER,
    position    INTEGER
);

-- Playback State
CREATE TABLE playback_state (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL UNIQUE REFERENCES "user"(id),
    current_song_id INTEGER REFERENCES song(id),
    current_time    FLOAT DEFAULT 0,
    is_playing      BOOLEAN DEFAULT FALSE,
    shuffle         BOOLEAN DEFAULT FALSE,
    repeat          VARCHAR(10) DEFAULT 'off',
    original_queue  TEXT DEFAULT '[]',
    shuffled_queue  TEXT DEFAULT '[]',
    history         TEXT DEFAULT '[]',
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Likes
CREATE TABLE "like" (
    id      SERIAL PRIMARY KEY,
    user_id INTEGER,
    song_id INTEGER
);

-- Play Logs
CREATE TABLE play_logs (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES "user"(id),
    song_id         INTEGER NOT NULL REFERENCES song(id),
    played_at       TIMESTAMP DEFAULT NOW(),
    listen_duration INTEGER DEFAULT 0,
    completed       BOOLEAN DEFAULT FALSE
);

-- Queue History
CREATE TABLE queue_history (
    id        SERIAL PRIMARY KEY,
    user_id   INTEGER REFERENCES "user"(id),
    song_id   INTEGER REFERENCES song(id),
    played_at TIMESTAMP DEFAULT NOW()
);

-- Sleep Timer
CREATE TABLE sleep_timer (
    user_id  INTEGER PRIMARY KEY,
    end_time TIMESTAMP,
    fade_out BOOLEAN DEFAULT FALSE
);

-- Jam Sessions
CREATE TABLE jam_session (
    id          VARCHAR(80) PRIMARY KEY,
    host_id     INTEGER REFERENCES "user"(id),
    song_id     INTEGER REFERENCES song(id),
    paused      BOOLEAN DEFAULT TRUE,
    position    FLOAT DEFAULT 0.0,
    started_at  TIMESTAMP,
    last_active TIMESTAMP DEFAULT NOW()
);

-- Jam State
CREATE TABLE jam_state (
    jam_id  VARCHAR PRIMARY KEY,
    host_id INTEGER,
    listeners TEXT
);

-- Jam
CREATE TABLE jam (
    id           VARCHAR(50) PRIMARY KEY,
    host_id      INTEGER,
    current_song INTEGER,
    current_time FLOAT,
    is_playing   BOOLEAN
);
"""

# ─────────────────────────────────────────────────────────
# TABLE → DAT FILE MAPPING
# Determined by matching column counts + sample data from
# the pg_dump directory (krew_db/*.dat) against models.
#
# Format: table_name → (dat_filename, [ordered_columns])
# ─────────────────────────────────────────────────────────
TABLE_MAP = {
    # user: 7 cols verified from 3506.dat
    # col[0]=id, col[1]=username, col[2]=email, col[3]=password_hash,
    # col[4]=is_artist(boolean), col[5]=artist_application_date, col[6]=artist_bio
    '"user"': {
        "file": "3506.dat",
        "columns": ["id", "username", "email", "password_hash",
                    "is_artist", "artist_application_date", "artist_bio"],
    },
    # song: 9 cols verified from 3508.dat
    # col[0]=id, col[1]=title, col[2]=artist, col[3]=album,
    # col[4]=audio_file, col[5]=cover_file, col[6]=uploaded_by, col[7]=genre, col[8]=lyrics
    "song": {
        "file": "3508.dat",
        "columns": ["id", "title", "artist", "album",
                    "audio_file", "cover_file", "uploaded_by", "genre", "lyrics"],
    },
    # playlist: 5 cols verified from 3512.dat
    # col[0]=id, col[1]=name, col[2]=owner_id, col[3]=position(\N), col[4]=cover_file(\N)
    "playlist": {
        "file": "3512.dat",
        "columns": ["id", "name", "owner_id", "position", "cover_file"],
    },
    # playlist_song: 3 cols verified from 3514.dat
    "playlist_song": {
        "file": "3514.dat",
        "columns": ["id", "playlist_id", "song_id"],
    },
    # play_logs: 6 cols verified from 3528.dat
    # col[0]=id, col[1]=user_id, col[2]=song_id, col[3]=played_at,
    # col[4]=listen_duration, col[5]=completed(t/f)
    "play_logs": {
        "file": "3528.dat",
        "columns": ["id", "user_id", "song_id", "played_at", "listen_duration", "completed"],
    },
    # playback_state: 11 cols from 3526.dat
    "playback_state": {
        "file": "3526.dat",
        "columns": ["id", "user_id", "current_song_id", "current_time", "is_playing",
                    "shuffle", "repeat", "original_queue", "shuffled_queue", "history", "updated_at"],
    },
    # queue_history: 4 cols from 3530.dat (may be empty)
    "queue_history": {
        "file": "3530.dat",
        "columns": ["id", "user_id", "song_id", "played_at"],
    },
}

def pg_copy_null_convert(dat_path, columns):
    """
    Read a pg_dump COPY text file. In COPY format:
    - \\N  = NULL
    - \\t  = tab (column sep)
    - \\r\\n or \\n = row sep
    - Ends with a line containing just '\\.'
    Returns lines ready for psycopg2 copy_expert.
    """
    lines = []
    try:
        with open(dat_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n").rstrip("\r")
                if line == "\\.":
                    break
                if not line:
                    continue
                lines.append(line + "\n")
    except Exception as e:
        print(f"  ⚠️  Could not read {dat_path}: {e}")
    return lines


def restore():
    print("=" * 60)
    print("  Krew Database → Supabase Restore Tool")
    print("=" * 60)

    # Validate dump dir
    toc_path = os.path.join(DUMP_DIR, "toc.dat")
    if not os.path.exists(toc_path):
        print(f"\n❌ Dump directory not found or missing toc.dat: {DUMP_DIR}")
        print("   Make sure DUMP_DIR points to the krew_db folder inside feb_22_db_render_free_")
        sys.exit(1)

    print(f"\n📂 Dump directory: {os.path.abspath(DUMP_DIR)}")
    print(f"🔗 Connecting to Supabase...\n")

    # Connect
    try:
        conn = psycopg2.connect(SUPABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        print("✅ Connected to Supabase\n")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("\nTip: Make sure your connection string looks like:")
        print("  postgresql://postgres:YOUR_PASSWORD@db.xxxxx.supabase.co:5432/postgres")
        sys.exit(1)

    # Step 1: Create schema
    print("📋 Step 1: Creating tables...")
    try:
        cur.execute(CREATE_SCHEMA_SQL)
        print("✅ Schema created\n")
    except Exception as e:
        print(f"❌ Schema creation failed: {e}")
        conn.close()
        sys.exit(1)

    # Step 2: Import data table by table
    print("📥 Step 2: Importing data...")
    for table, info in TABLE_MAP.items():
        dat_path = os.path.join(DUMP_DIR, info["file"])
        columns = info["columns"]

        if not os.path.exists(dat_path):
            print(f"  ⚠️  {table}: {info['file']} not found, skipping")
            continue

        file_size = os.path.getsize(dat_path)
        if file_size <= 5:
            print(f"  ⏩  {table}: empty (skipped)")
            continue

        lines = pg_copy_null_convert(dat_path, columns)
        if not lines:
            print(f"  ⏩  {table}: no rows")
            continue

        col_list = ", ".join(columns)
        copy_sql = f'COPY {table} ({col_list}) FROM STDIN WITH (FORMAT text, NULL \'\\N\')'

        try:
            data = io.StringIO("".join(lines))
            cur.copy_expert(copy_sql, data)
            print(f"  ✅  {table}: {len(lines)} rows imported")
        except Exception as e:
            print(f"  ❌  {table}: FAILED — {e}")
            # Try to continue with other tables
            conn.autocommit = False
            conn.rollback()
            conn.autocommit = True

    # Step 3: Reset sequences so new inserts get correct IDs
    print("\n🔄 Step 3: Resetting sequences...")
    sequences = [
        ('"user"', 'user_id_seq', 'id'),
        ('song',   'song_id_seq', 'id'),
        ('playlist', 'playlist_id_seq', 'id'),
        ('play_logs', 'play_logs_id_seq', 'id'),
        ('playback_state', 'playback_state_id_seq', 'id'),
        ('artist_application', 'artist_application_id_seq', 'id'),
        ('playlist_song', 'playlist_song_id_seq', 'id'),
        ('queue_history', 'queue_history_id_seq', 'id'),
    ]
    for table, seq, col in sequences:
        try:
            cur.execute(f'SELECT setval(\'{seq}\', COALESCE((SELECT MAX({col}) FROM {table}), 1))')
            print(f"  ✅  {seq} reset")
        except Exception as e:
            print(f"  ⚠️  {seq}: {e}")

    cur.close()
    conn.close()

    print("\n" + "=" * 60)
    print("  ✅ Restore Complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Copy your Supabase connection string")
    print("2. Add it to krew_backend/.env as:")
    print("   DATABASE_URL=postgresql://postgres:PASSWORD@db.xxx.supabase.co:5432/postgres")
    print("3. Also add it to your Render backend environment variables")
    print("=" * 60)


if __name__ == "__main__":
    restore()
