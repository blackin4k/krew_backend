import re

LOG_FILE = "deletion_log.txt"

def generate_sql():
    files_to_delete = []
    
    # Simple parsing: look for lines starting with "  DELETE: "
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("DELETE:"):
                    # line format: "  DELETE: filename.mp3"
                    # split by ": " and take the second part
                    parts = line.split(": ", 1)
                    if len(parts) > 1:
                        filename = parts[1].strip()
                        files_to_delete.append(filename)
    except FileNotFoundError:
        print(f"Error: Could not find {LOG_FILE}")
        return

    if not files_to_delete:
        print("No files found to delete in log.")
        return

    # Escape single quotes in filenames for SQL
    escaped_files = []
    for f in files_to_delete:
        safe_f = f.replace("'", "''")
        escaped_files.append(f"'{safe_f}'")
    
    # Construct PL/pgSQL block
    sql = "DO $$\n"
    sql += "DECLARE\n"
    sql += "    target_song_ids INTEGER[];\n"
    sql += "BEGIN\n"
    sql += "    -- 1. Identify IDs of songs to be deleted\n"
    sql += "    SELECT ARRAY(\n"
    sql += "        SELECT id FROM song WHERE audio_file IN (\n"
    sql += "            " + ",\n            ".join(escaped_files) + "\n"
    sql += "        )\n"
    sql += "    ) INTO target_song_ids;\n\n"
    
    sql += "    -- 2. Delete/Update references in dependent tables\n"
    sql += "    IF array_length(target_song_ids, 1) > 0 THEN\n"
    sql += "        DELETE FROM play_logs WHERE song_id = ANY(target_song_ids);\n"
    sql += "        DELETE FROM playlist_song WHERE song_id = ANY(target_song_ids);\n"
    sql += "        DELETE FROM \"like\" WHERE song_id = ANY(target_song_ids);\n"
    sql += "        DELETE FROM queue_history WHERE song_id = ANY(target_song_ids);\n"
    sql += "        UPDATE playback_state SET current_song_id = NULL WHERE current_song_id = ANY(target_song_ids);\n"
    sql += "        UPDATE external_playlist_track SET song_id = NULL WHERE song_id = ANY(target_song_ids);\n\n"
    
    sql += "        -- 3. Delete from main song table\n"
    sql += "        DELETE FROM song WHERE id = ANY(target_song_ids);\n"
    sql += "    END IF;\n"
    sql += "END $$;"
    
    with open("deletion_query.sql", "w", encoding="utf-8") as f:
        f.write(sql)
    print("SQL command written to deletion_query.sql")

if __name__ == "__main__":
    generate_sql()
