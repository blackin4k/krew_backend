from app import app, db, Song
from sqlalchemy import func

def analyze():
    with app.app_context():
        # 1. Check Extensions
        print("--- File Extensions in Database ---")
        # SQL equivalent: SELECT substring(audio_file from '\.[^.]+$'), count(*) ...
        # In python we can just fetch all and process, or use SQL.
        # Let's fetch all audio_files (it's not that big, ~170 rows based on duplicates file)
        songs = db.session.query(Song.audio_file).all()
        
        extensions = {}
        for (filename,) in songs:
            if not filename:
                ext = "None"
            elif "." in filename:
                ext = filename.split(".")[-1].lower()
            else:
                ext = "No Extension"
            
            extensions[ext] = extensions.get(ext, 0) + 1
            
        for ext, count in extensions.items():
            print(f".{ext}: {count} files")
            
        # 2. Check for a known deleted duplicate
        # Example: '112 - The Weeknd - Acquainted.mp3'
        print("\n--- Checking for deleted duplicates ---")
        target = '112 - The Weeknd - Acquainted.mp3'
        exists = Song.query.filter_by(audio_file=target).first()
        if exists:
            print(f"WARNING: '{target}' IS STILL IN THE DATABASE (ID: {exists.id})")
        else:
            print(f"CONFIRMED: '{target}' is NOT in the database.")

if __name__ == "__main__":
    analyze()
