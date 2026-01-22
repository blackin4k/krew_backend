from app import app, db, Song

with app.app_context():
    count = Song.query.count()
    print(f"Total Songs in DB: {count}")
