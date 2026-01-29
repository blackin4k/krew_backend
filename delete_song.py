
import os
import sys
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Minimal Setup to avoid importing 'app' which needs gevent/eventlet
app = Flask(__name__)
database_url = os.environ.get("DATABASE_URL")
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = database_url or "sqlite:///instance/db.sqlite3"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    artist = db.Column(db.String(200), nullable=False)
    album = db.Column(db.String(200))
    audio_file = db.Column(db.String(500), nullable=False)
    cover_file = db.Column(db.String(500))
    genre = db.Column(db.String(100))
    uploaded_by = db.Column(db.Integer)
    lyrics = db.Column(db.Text, nullable=True)

def delete_song(song_id):
    with app.app_context():
        song = Song.query.get(song_id)
        if song:
            print(f"🗑️ Deleting: {song.title} (ID: {song.id})")
            db.session.delete(song)
            db.session.commit()
            print("✅ Deleted successfully.")
        else:
            print(f"⚠️ Song ID {song_id} not found.")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        s_id = int(sys.argv[1])
        delete_song(s_id)
    else:
        print("Usage: python delete_song.py <song_id>")
