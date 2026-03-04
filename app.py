 # =========================================================
# KREW -BACKEND — VERSION 3
# =========================================================

# -------------------------
from gevent import monkey
monkey.patch_all()

import os
import math
import time
import json
import uuid
import threading
import requests
from datetime import datetime, timedelta
import random
import hashlib
from collections import defaultdict, Counter
from flask_jwt_extended import decode_token
from sqlalchemy import or_, func, case, desc
import boto3 # Added for R2
from sync_to_render import sync_songs # Added for Auto-Sync
from dotenv import load_dotenv
load_dotenv() # Load environment variables

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TCON, APIC
from mutagen.flac import FLAC
from mutagen.wave import WAVE

from sqlalchemy.exc import IntegrityError
from flask import Flask, request, jsonify, send_file, send_from_directory, redirect, stream_with_context
from flask import Response
from flask_sqlalchemy import SQLAlchemy
import difflib # For fuzzy search
from flask_jwt_extended import (
    JWTManager, create_access_token,
    jwt_required, get_jwt_identity, verify_jwt_in_request
)
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, join_room, emit
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_cors import CORS

# =========================================================
# PATHS + APP CONFIG (ORDER MATTERS)
# =========================================================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
STATIC_DIR = os.path.join(BASE_DIR, "static")
AUDIO_DIR = os.path.join(STATIC_DIR, "audio")
COVER_DIR = os.path.join(STATIC_DIR, "covers")
os.makedirs(INSTANCE_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(COVER_DIR, exist_ok=True)

app = Flask(__name__)

# Configure CORS
# CORS handled manually below for maximum compatibility with mobile apps
# CORS(app) - configuration removed in favor of manual headers

# Database configuration - PostgreSQL in production, SQLite in development
database_url = os.environ.get("DATABASE_URL")
if database_url:
    # Render provides DATABASE_URL, but it starts with postgres:// instead of postgresql://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
else:
    # Local development uses SQLite
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{os.path.join(INSTANCE_DIR, 'db.sqlite3')}"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# SECURITY: JWT secret must come from environment in production
# Only allow auto-generated secret in development
jwt_secret = os.environ.get("JWT_SECRET_KEY")
if not jwt_secret:
    if os.environ.get("FLASK_ENV") == "production" or os.environ.get("RENDER"):
        raise RuntimeError("CRITICAL: JWT_SECRET_KEY must be set in production!")
    # Dev only: generate a random secret (tokens won't persist across restarts)
    import secrets
    jwt_secret = secrets.token_hex(32)
    print("⚠️  DEV MODE: Using auto-generated JWT secret (tokens won't persist)")
app.config["JWT_SECRET_KEY"] = jwt_secret
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = 604800  # 7 days in seconds

app.config["UPLOAD_AUDIO"] = AUDIO_DIR
app.config["UPLOAD_COVER"] = COVER_DIR

@app.route("/ping_top")
def ping_top():
    return jsonify(msg="pong_top")

# =========================================================
# ADMIN UPLOAD ROUTE
# =========================================================
from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS_AUDIO = {'mp3', 'wav', 'flac', 'm4a', 'ogg'}
ALLOWED_EXTENSIONS_COVER = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename, allowed_set):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_set

# R2 Configuration
R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "krew-music")

# Initialize Global S3 Client for Presigned URLs
s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT_URL,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    region_name="auto"
)

def extract_metadata(file_path):
    """
    Extracts title, artist, album, genre from audio file using mutagen.
    Returns a dict with found values (None if missing).
    """
    meta = {"title": None, "artist": None, "album": None, "genre": None}
    try:
        if file_path.lower().endswith(".mp3"):
            audio = MP3(file_path, ID3=ID3)
            if audio.tags:
                meta["title"] = str(audio.tags.get("TIT2")) if audio.tags.get("TIT2") else None
                meta["artist"] = str(audio.tags.get("TPE1")) if audio.tags.get("TPE1") else None
                meta["album"] = str(audio.tags.get("TALB")) if audio.tags.get("TALB") else None
                meta["genre"] = str(audio.tags.get("TCON")) if audio.tags.get("TCON") else None
        # Add FLAC/WAV support if needed here
    except Exception as e:
        print(f"⚠️ Metadata extraction failed: {e}")
    return meta

def upload_to_r2(local_path, r2_path):
    try:
        # Use global client
        s3_client.upload_file(local_path, R2_BUCKET_NAME, r2_path)
        print(f"✅ Uploaded to R2: {r2_path}")
        return True
    except Exception as e:
        print(f"❌ R2 Upload Failed: {e}")
        return False

@app.route("/songs/upload", methods=["POST"])
@jwt_required()
def upload_song():
    try:
        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        
        if not user or not user.is_artist:
            return jsonify(error="Unauthorized: Only approved artists can upload songs."), 403

        if 'audio' not in request.files:
            return jsonify(error="No audio file part"), 400
        
        file = request.files['audio']
        cover = request.files.get('cover') # Optional

        title = request.form.get('title')
        artist = request.form.get('artist', user.username) # Default to username if not provided
        album = request.form.get('album', 'Single')
        lyrics = request.form.get('lyrics', '')

        if file.filename == '':
            return jsonify(error="No selected file"), 400

        if file and allowed_file(file.filename, ALLOWED_EXTENSIONS_AUDIO):
            filename = secure_filename(file.filename)
            unique_id = str(uuid.uuid4())[:8]
            filename = f"{unique_id}_{filename}"
            
            file.save(os.path.join(app.config['UPLOAD_AUDIO'], filename))

            cover_filename = None
            if cover and allowed_file(cover.filename, ALLOWED_EXTENSIONS_COVER):
                cover_fname = secure_filename(cover.filename)
                cover_fname = f"{unique_id}_{cover_fname}"
                cover.save(os.path.join(app.config['UPLOAD_COVER'], cover_fname))
                cover_filename = cover_fname
            
            # Metadata Strategy (Simplified)
            # 1. Start with Form Data (User provided)
            # 2. Fallback to Auto-Extraction
            extracted_meta = extract_metadata(os.path.join(app.config['UPLOAD_AUDIO'], filename))
            
            final_title = title if title else (extracted_meta["title"] if extracted_meta["title"] else os.path.splitext(request.files['audio'].filename)[0])
            final_artist = artist if artist else (extracted_meta["artist"] if extracted_meta["artist"] else user.username)
            final_album = album if album else (extracted_meta["album"] if extracted_meta["album"] else "Unknown")
            
            form_genre = request.form.get('genre')
            final_genre = form_genre if form_genre else (extracted_meta["genre"] if extracted_meta["genre"] else "Unknown")

            # Create Song Record
            new_song = Song(
                title=final_title,
                artist=final_artist,
                album=final_album,
                audio_file=filename,
                cover_file=cover_filename,
                genre=final_genre,
                lyrics=lyrics,
                uploaded_by=user.id 
            )
            
            db.session.add(new_song)
            db.session.commit()

            # --- AUTO-SYNC TO PROD ---
            # (In a real app, maybe offset this to a worker, but keeping it simple)
            try:
                # 1. Upload to R2
                audio_path = os.path.join(app.config['UPLOAD_AUDIO'], filename)
                upload_to_r2(audio_path, f"audio/{filename}")
                if cover_filename:
                    cover_path = os.path.join(app.config['UPLOAD_COVER'], cover_filename)
                    upload_to_r2(cover_path, f"covers/{cover_filename}")

                # 2. Sync Database
                sync_songs()
            except Exception as e:
                print(f"❌ Sync Warning: {e}")
                # Don't fail the request if sync fails, just log it

            return jsonify({
                "msg": "Song uploaded successfully!", 
                "song": {
                    "id": new_song.id,
                    "title": new_song.title,
                    "artist": new_song.artist
                }
            }), 201

    except Exception as e:
        print(f"Upload Error: {e}")
        return jsonify(error=str(e)), 500

@app.route("/admin/upload", methods=["POST"])
def admin_upload_song():
    # Simple Security Check (Replace "krew_admin_secret" with a real env var in prod)
    admin_secret = request.headers.get("X-Admin-Secret")
    if admin_secret != os.environ.get("ADMIN_SECRET", "krew_dev_admin_123"):
        return jsonify(error="Unauthorized"), 401


    if 'audio' not in request.files:
        return jsonify(error="No audio file part"), 400
    
    file = request.files['audio']
    cover = request.files.get('cover') # Optional

    title = request.form.get('title')
    artist = request.form.get('artist', 'Unknown Artist')
    album = request.form.get('album', 'Unknown Album')
    lyrics = request.form.get('lyrics', '')

    if file.filename == '':
        return jsonify(error="No selected file"), 400

    if file and allowed_file(file.filename, ALLOWED_EXTENSIONS_AUDIO):
        filename = secure_filename(file.filename)
        # Ensure unique filename to prevent overwrites
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{unique_id}_{filename}"
        
        file.save(os.path.join(app.config['UPLOAD_AUDIO'], filename))

        cover_filename = None
        if cover and allowed_file(cover.filename, ALLOWED_EXTENSIONS_COVER):
            cover_fname = secure_filename(cover.filename)
            cover_fname = f"{unique_id}_{cover_fname}"
            cover.save(os.path.join(app.config['UPLOAD_COVER'], cover_fname))
            cover_filename = cover_fname
        
        # Metadata Strategy:
        # 1. Start with Form Data (User provided)
        # 2. If missing, try Auto-Extraction from file
        # 3. Fallback to Defaults
        
        extracted_meta = extract_metadata(os.path.join(app.config['UPLOAD_AUDIO'], filename))
        
        final_title = title if title else (extracted_meta["title"] if extracted_meta["title"] else os.path.splitext(request.files['audio'].filename)[0])
        final_artist = artist if artist and artist != "Unknown Artist" else (extracted_meta["artist"] if extracted_meta["artist"] else "Unknown Artist")
        final_album = album if album and album != "Unknown Album" else (extracted_meta["album"] if extracted_meta["album"] else "Unknown Album")
        
        # FIX: Respect form genre, fallback to extracted, default to "Unknown" (NOT "Uploaded")
        form_genre = request.form.get('genre')
        final_genre = form_genre if form_genre else (extracted_meta["genre"] if extracted_meta["genre"] else "Unknown")

        # Create Song Record
        new_song = Song(
            title=final_title,
            artist=final_artist,
            album=final_album,
            audio_file=filename,
            cover_file=cover_filename,
            genre=final_genre,
            lyrics=lyrics,
            uploaded_by=0 # 0 for Admin
        )
        
        db.session.add(new_song)
        db.session.commit()

        # --- AUTO-SYNC TO PROD ---
        print("🔄 Starting Auto-Sync to Production...")
        
        # 1. Upload Files to R2
        audio_path = os.path.join(app.config['UPLOAD_AUDIO'], filename)
        upload_to_r2(audio_path, f"audio/{filename}")
        
        if cover_filename:
            cover_path = os.path.join(app.config['UPLOAD_COVER'], cover_filename)
            upload_to_r2(cover_path, f"covers/{cover_filename}")

        # 2. Sync Database to Render
        try:
            sync_songs()
        except Exception as e:
            print(f"❌ DB Sync Failed: {e}")
            return jsonify({
                "msg": "Song saved locally but Sync failed.", 
                "error": str(e),
                "song": {"id": new_song.id, "title": new_song.title}
            }), 201

        return jsonify({
            "msg": "Song uploaded & Synced to Live App! 🚀", 
            "song": {
                "id": new_song.id,
                "title": new_song.title,
                "artist": new_song.artist
            }
        }), 201

    return jsonify(error="Invalid file type"), 400

# MOVED PLAYER ROUTES TO FIX NEXT/PREV
@app.route("/player/play", methods=["POST"])
@jwt_required()
def player_play_top():
    user_id = int(get_jwt_identity())
    data = request.json or {}
    if "song_id" not in data:
        return jsonify(error="song_id required"), 400
        
    song_id = int(data["song_id"])
    state = PlaybackState.query.filter_by(user_id=user_id).first()
    if not state:
         # Auto-create state if missing
         state = PlaybackState(user_id=user_id)
         db.session.add(state)

    # 1. Update History (Push OLD song)
    if state.current_song_id and state.current_song_id != song_id:
        try:
            hist = json.loads(state.history or "[]")
        except: hist = []
        # Prevent duplicate top-of-stack push if user spams click
        if not hist or hist[-1] != state.current_song_id:
            hist.append(state.current_song_id)
            if len(hist) > 50: hist.pop(0)
            state.history = json.dumps(hist)

    # 2. Update Current
    state.current_song_id = song_id

    # 3. Remove new song from Queue (so Next doesn't repeat it)
    # This is critical for "Next button plays same song" fix
    try:
        queue = json.loads(state.shuffled_queue if state.shuffle else state.original_queue)
    except: queue = []
    
    if song_id in queue:
        queue = [s for s in queue if s != song_id]
        if state.shuffle: state.shuffled_queue = json.dumps(queue)
        else: state.original_queue = json.dumps(queue)

    db.session.commit()

    song = Song.query.get(song_id)
    if not song: return jsonify(error="Song not found"), 404

    # CORS FIX: Always route through our proxy endpoint
    # This prevents the frontend from hitting R2 directly (which lacks CORS headers)
    audio_url = full_url(f"/songs/{song.id}/stream")
    cover_url = get_presigned_url(song.cover_file, "covers") if song.cover_file else None

    return jsonify({
        "id": song.id,
        "title": song.title,
        "artist": song.artist,
        "cover": cover_url,
        "audio": audio_url
    })

@app.route("/player/next", methods=["POST"])
@jwt_required()
def player_next_top():
    user_id = int(get_jwt_identity())
    state = PlaybackState.query.filter_by(user_id=user_id).first()
    if not state: return jsonify(error="No state"), 404
    
    try:
        queue = json.loads(state.shuffled_queue if state.shuffle else state.original_queue)
    except: queue = []

    if not queue:
        autoplay_fill(state)
        try:
            queue = json.loads(state.shuffled_queue if state.shuffle else state.original_queue)
        except: queue = []
    
    if not queue: return jsonify(error="Queue empty"), 400

    if state.current_song_id:
        try:
            hist = json.loads(state.history or "[]")
        except: hist = []
        hist.append(state.current_song_id)
        if len(hist) > 50: hist.pop(0)
        state.history = json.dumps(hist)

    # -------------------------------------------------------
    # LOOP TO SKIP DELETED/INVALID SONGS
    # -------------------------------------------------------
    next_id = None
    song = None
    
    while queue:
        candidate_id = queue.pop(0)
        song = Song.query.get(candidate_id)
        if song:
            next_id = candidate_id
            break
        # If song is None (deleted), loop continues and pops next
    
    # Save the updated queue (with deleted songs removed)
    if state.shuffle:
        state.shuffled_queue = json.dumps(queue)
    else:
        state.original_queue = json.dumps(queue)

    if not next_id or not song:
        db.session.commit()
        return jsonify(error="Queue empty (valid songs)"), 400

    state.current_song_id = next_id
    db.session.commit()
    
    return jsonify({
        "id": song.id,
        "title": song.title,
        "artist": song.artist,
        "cover": get_presigned_url(song.cover_file, "covers") if song.cover_file else None,
        "audio": full_url(f"/songs/{song.id}/stream")
    })

@app.route("/player/prev", methods=["POST"])
@jwt_required()
def player_prev_top():
    user_id = int(get_jwt_identity())
    state = PlaybackState.query.filter_by(user_id=user_id).first()
    if not state: return jsonify(error="No state"), 404

    try:
        hist = json.loads(state.history or "[]")
    except: hist = []
    
    # -------------------------------------------------------
    # LOOP BACKWARDS TO FIND VALID SONG
    # -------------------------------------------------------
    prev_id = None
    song = None
    
    while hist:
        candidate_id = hist.pop() # Pop from end (most recent)
        song = Song.query.get(candidate_id)
        if song:
            prev_id = candidate_id
            break
        # If deleted, continue popping
    
    state.history = json.dumps(hist)

    if not prev_id or not song:
        # No valid history left, verify current song still exists
        if state.current_song_id:
             current_song = Song.query.get(state.current_song_id)
             if current_song:
                 return jsonify({
                    "id": current_song.id,
                    "title": current_song.title,
                    "artist": current_song.artist,
                    "cover": get_presigned_url(current_song.cover_file, "covers") if current_song.cover_file else None,
                    "audio": full_url(f"/songs/{current_song.id}/stream")
                 })
        return jsonify(error="No history"), 400

    # Found a valid previous song
    if state.current_song_id:
        try:
            queue = json.loads(state.shuffled_queue if state.shuffle else state.original_queue)
        except: queue = []
        queue.insert(0, state.current_song_id)
        if state.shuffle: state.shuffled_queue = json.dumps(queue)
        else: state.original_queue = json.dumps(queue)

    state.current_song_id = prev_id
    db.session.commit()

    return jsonify({
        "id": song.id,
        "title": song.title,
        "artist": song.artist,
        "cover": get_presigned_url(song.cover_file, "covers") if song.cover_file else None,
        "audio": full_url(f"/songs/{song.id}/stream")
    })

# MOVED ROUTES TO FIX 404
@app.route("/player/record-play", methods=["POST", "OPTIONS"])
def record_play_top():
    if request.method == "OPTIONS":
        return jsonify(msg="Preflight OK")

    verify_jwt_in_request()
    user_id = int(get_jwt_identity())
    data = request.json or {}
    song_id = data.get("song_id")
    duration = data.get("duration", 0) # Accept duration, default to 0

    if not song_id:
        return jsonify(error="song_id required"), 400
    
    try:
        song_id = int(song_id) 
        song = Song.query.get(song_id)
        if not song:
            return jsonify(msg="Song ignored"), 200

        log = PlayLog(
            user_id=user_id,
            song_id=song_id,
            played_at=datetime.utcnow(),
            completed=True,
            listen_duration=int(duration) # Store actual duration
        )
        db.session.add(log)
        db.session.commit()
        return jsonify(msg="Recorded")
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route("/me", methods=["GET"])
@jwt_required()
def get_user_profile_top():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify(error="User not found"), 404
        
    return jsonify({
        "id": user.id,
        "username": user.username,
        "email": user.email
    })

@app.route("/artists/<path:name>", methods=["GET"])
@jwt_required()
def get_artist_profile(name):
    # Decode name safely
    from urllib.parse import unquote
    artist_name = unquote(name)
    
    # 1. Get Songs by Artist
    songs = Song.query.filter(func.lower(Song.artist) == artist_name.lower()).all()
    
    if not songs:
        # Fuzzy match fallback? Or just 404? 
        return jsonify(error="Artist not found"), 404

    # 2. Get Bio from User table (if claimed)
    # Try to find a user whose username matches or is linked
    # For now, strict match on username or we could add an 'artist_name' field to User later
    artist_user = User.query.filter(func.lower(User.username) == artist_name.lower(), User.is_artist == True).first()
    bio = artist_user.artist_bio if artist_user else "Approved Krew Artist"

    # 3. Calculate Stats
    total_plays = (
        db.session.query(func.count(PlayLog.id))
        .join(Song, PlayLog.song_id == Song.id)
        .filter(func.lower(Song.artist) == artist_name.lower())
        .scalar()
    ) or 0
    
    # 4. Top Songs (by plays)
    top_songs_res = (
        db.session.query(Song, func.count(PlayLog.id).label("plays"))
        .outerjoin(PlayLog, PlayLog.song_id == Song.id)
        .filter(func.lower(Song.artist) == artist_name.lower())
        .group_by(Song.id)
        .order_by(desc("plays"))
        .limit(5)
        .all()
    )
    
    top_songs = [{
        "id": s.id,
        "title": s.title,
        "album": s.album,
        "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
        "plays": plays
    } for s, plays in top_songs_res]

    # 5. Albums
    albums = list(set([s.album for s in songs if s.album]))
    
    return jsonify({
        "name": songs[0].artist, # Use DB casing
        "bio": bio,
        "monthly_listeners": int(total_plays * 0.4), # Fake 'monthly' stat derived from total
        "total_plays": total_plays,
        "top_songs": top_songs,
        "albums": albums,
        "similar_artists": [] # Placeholder
    })

# =========================================================
# EXTENSIONS (MUST COME BEFORE MODELS)
# =========================================================
db = SQLAlchemy(app)
jwt = JWTManager(app)
bcrypt = Bcrypt(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Rate limiting
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")
limiter.init_app(app)

import os
import re
is_dev = os.environ.get("FLASK_ENV") != "production"

# Enforce secret in production
if not is_dev and not os.environ.get("JWT_SECRET_KEY"):
    raise RuntimeError("JWT_SECRET_KEY must be set in production.")
# CORS handled manually for maximum compatibility
# Note: dynamic origin reflection is required for withCredentials=true

def is_allowed_origin(origin):
    # TEMPORARY: Allow EVERYTHING to debug mobile data issues
    return True

@app.before_request
def handle_options_request():
    if request.method == "OPTIONS":
        origin = request.headers.get("Origin", "*")
        response = Response()
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, ngrok-skip-browser-warning"
        return response

@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept, ngrok-skip-browser-warning"
    return response


def get_current_position(jam_id):
    # Changed: guard against missing state/started_at and return a float position
    state = jam_state.get(jam_id)
    if not state:
        return 0.0
    if state.get("paused"):
        return float(state.get("position", 0.0))
    if not state.get("started_at"):
        return float(state.get("position", 0.0))
    elapsed = (datetime.utcnow() - state["started_at"]).total_seconds()
    return float(state.get("position", 0.0) + elapsed)

@app.before_request
def log_request_info():
    if request.path.startswith("/playlists/import"):
        print(f"Incoming {request.method} to {request.path}")
        print(f"Origin: {request.headers.get('Origin')}")



# =========================================================
# DISCORD PRESENCE (Disabled for deployment)
# =========================================================
# from pypresence import Presence
# import threading
# 
# DISCORD_CLIENT_ID = '1330458763539513364'
# 
# class DiscordService:
#     def __init__(self, client_id):
#         self.client_id = client_id
#         self.rpc = None
#         self.connected = False
#         self.last_track = None
# 
#     def connect(self):
#         try:
#             self.rpc = Presence(self.client_id)
#             self.rpc.connect()
#             self.connected = True
#             print("Discord RPC Connected")
#         except:
#             self.connected = False
# 
#     def update(self, title, artist):
#         if self.last_track == (title, artist):
#             return
# 
#         def _update():
#             if not self.connected:
#                 self.connect()
#             
#             if self.connected:
#                 try:
#                     self.rpc.update(
#                         details=title[:128],
#                         state=artist[:128],
#                         large_image="krew_logo",
#                         large_text="Krew Music",
#                         small_image="play_icon",
#                         small_text="Listening"
#                     )
#                     self.last_track = (title, artist)
#                 except:
#                     self.connected = False
#         
#         threading.Thread(target=_update, daemon=True).start()
# 
# discord_service = DiscordService(DISCORD_CLIENT_ID) 
# threading.Thread(target=discord_service.connect, daemon=True).start()


def full_url(path):
    return request.host_url.rstrip("/") + path

# R2 Storage Configuration
# R2 Storage Configuration
raw_r2_url = os.environ.get("R2_PUBLIC_URL", "https://pub-5e22fa30a7744b769bea5ad23240ed75.r2.dev")
R2_PUBLIC_URL = raw_r2_url.strip().strip("'").strip('"').rstrip("/")

# Simple in-memory cache for presigned URLs (cleared hourly or on restart)
# Key: (filename, folder), Value: (url, timestamp)
from functools import lru_cache
import time

@lru_cache(maxsize=1000)
def _cached_presigned_url(filename, folder, cache_bucket):
    """
    Generate presigned URL with caching.
    cache_bucket: hour bucket (changes every hour to invalidate cache)
    """
    key = filename
    if not key.startswith(f"{folder}/"):
        key = f"{folder}/{filename}"
    
    try:
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={'Bucket': R2_BUCKET_NAME, 'Key': key},
            ExpiresIn=3600  # URL valid for 1 hour
        )
        return url
    except Exception as e:
        print(f"❌ Presigned URL Gen Failed for {key}: {e}")
        from urllib.parse import quote
        safe_key = quote(key)
        return f"{R2_PUBLIC_URL}/{safe_key}"

def get_presigned_url(filename, folder):
    """
    Returns a Public R2 URL for faster loading (cached by CDN).
    Falls back to presigned if R2_PUBLIC_URL is not set (but it should be).
    """
    if not filename: return None
    if filename.startswith("http"): return filename
    
    # 🚀 ACCELERATION: Use Public URL (No boto3 overhead, Cacheable)
    # DISABLED: Causing 401s because bucket might not be correctly public.
    # if R2_PUBLIC_URL:
    #     from urllib.parse import quote
    #     # R2/S3 keys are case sensitive. Our folder structure is "audio/" and "covers/"
    #     # Ensure we don't double up the folder if it's already in the filename (legacy data)
    #     key = filename
    #     if not key.startswith(f"{folder}/"):
    #         key = f"{folder}/{filename}"
            
    #     safe_key = quote(key)
    #     return f"{R2_PUBLIC_URL}/{safe_key}"
            
    # Fallback to slow presigned URL
    # Use hour as cache bucket - cache invalidates when hour changes

    cache_bucket = int(time.time() // 3600)
    return _cached_presigned_url(filename, folder, cache_bucket)

# =========================================================
# HELPER: Generate Full URL (HTTPS Aware for Render)
# =========================================================
def full_url(path):
    """
    Generates a full URL for a given path, respecting X-Forwarded-Proto
    to ensure HTTPS on Render/Production.
    """
    if not path.startswith("/"):
        path = f"/{path}"
        
    # Check for Render/Proxy headers
    scheme = request.headers.get("X-Forwarded-Proto", request.scheme)
    host = request.headers.get("Host", request.host)
    
    # Force HTTPS on production domains if not present
    if "kreewaux.xyz" in host and scheme == "http":
        scheme = "https"
        
    return f"{scheme}://{host}{path}"


@app.route("/covers/<path:filename>")
def cover(filename):
    # REDIRECT to R2 (Offload traffic from backend)
    # Proxying images was killing server threads and causing timeouts
    # Browser will fetch from R2 directly with a signed URL
    url = get_presigned_url(filename, "covers")
    if url: 
        return redirect(url)
    
    # Fallback
    print(f"⚠️ Cover not found in R2 Presign, checking local: {filename}")
    return send_file(os.path.join(COVER_DIR, filename))


@app.route("/audio/<path:filename>")
def serve_audio(filename):
    # Redirect to R2 + Cache
    # NOTE: This endpoint directs to R2. 
    # The /songs/<id>/stream endpoint uses the proxy.
    url = get_presigned_url(filename, "audio")
    if url: 
        resp = redirect(url)
        resp.headers['Cache-Control'] = 'public, max-age=3000'
        return resp
        
    return send_from_directory(AUDIO_DIR, filename)
from werkzeug.exceptions import HTTPException

@app.errorhandler(Exception)
def handle_error(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    return jsonify(error=str(e)), 500

@app.route("/health")
def health_check():
    return jsonify(status="ok", timestamp=datetime.utcnow().isoformat())

@app.route("/playlists/<int:pid>/full", methods=["GET"])
@jwt_required()
def get_full_playlist(pid):
    user_id = int(get_jwt_identity())
    playlist = Playlist.query.get_or_404(pid)

    if playlist.owner_id != user_id:
        return jsonify(error="Forbidden"), 403

    songs = (
        db.session.query(Song)
        .join(PlaylistSong, Song.id == PlaylistSong.song_id)
        .filter(PlaylistSong.playlist_id == pid)
        .all()
    )

    missing = ExternalPlaylistTrack.query.filter_by(
        playlist_id=pid,
        available=False
    ).all()

    return jsonify({
        "id": playlist.id,
        "name": playlist.name,
        "available": [
            {
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "playable": True
            } for s in songs
        ],
        "unavailable": [
            {
                "title": m.title,
                "artist": m.artist,
                "playable": False
            } for m in missing
        ]
    })

# =========================================================
# DATABASE MODELS
# =========================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    
    # Artist verification fields
    is_artist = db.Column(db.Boolean, default=False)
    artist_application_date = db.Column(db.DateTime, nullable=True)
    artist_bio = db.Column(db.Text, nullable=True)


class ArtistApplication(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    artist_name = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text, nullable=False)
    social_links = db.Column(db.Text, nullable=True)  # JSON string of social media links
    sample_work_url = db.Column(db.String(500), nullable=True)  # Optional link to existing work
    status = db.Column(db.String(20), default='pending')  # pending, approved, rejected
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, nullable=True)  # admin user_id


class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(200), index=True)
    artist = db.Column(db.String(200), index=True)
    album = db.Column(db.String(200), index=True)

    audio_file = db.Column(db.String(255))
    cover_file = db.Column(db.String(255))
    uploaded_by = db.Column(db.Integer)
    genre = db.Column(db.String(50), default="Unknown", index=True)
    lyrics = db.Column(db.Text, nullable=True)
    
    # New columns for analytics and duplication check
    duration = db.Column(db.Integer, default=0)
    play_count = db.Column(db.Integer, default=0)
    audio_hash = db.Column(db.String(64), index=True)


class ExternalPlaylistTrack(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlist.id'))
    title = db.Column(db.String(200))
    artist = db.Column(db.String(200))
    available = db.Column(db.Boolean, default=False)
    song_id = db.Column(db.Integer, nullable=True)
    position = db.Column(db.Integer)





class Playlist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200))
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    position = db.Column(db.Integer)
    cover_file = db.Column(db.String(255))


class PlaylistSong(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey('playlist.id'))
    song_id = db.Column(db.Integer, db.ForeignKey('song.id'))



class PlaybackState(db.Model):
    __tablename__ = "playback_state"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)

    current_song_id = db.Column(db.Integer, db.ForeignKey("song.id"), nullable=True)
    current_time = db.Column(db.Float, default=0)
    is_playing = db.Column(db.Boolean, default=False)

    shuffle = db.Column(db.Boolean, default=False)
    repeat = db.Column(db.String(10), default="off")  # off | all | one

    original_queue = db.Column(db.Text, default="[]")   # JSON list
    shuffled_queue = db.Column(db.Text, default="[]")   # JSON list
    history = db.Column(db.Text, default="[]")          # JSON list: [id, id, id] (Stack)

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Artist(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True)

    image_url = db.Column(db.String(500))
    bio = db.Column(db.Text)

    last_updated = db.Column(db.DateTime)


class Like(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    song_id = db.Column(db.Integer, db.ForeignKey("song.id"))


class Jam(db.Model):
    id = db.Column(db.String(50), primary_key=True)
    host_id = db.Column(db.Integer)
    current_song = db.Column(db.Integer)
    current_time = db.Column(db.Float)
    is_playing = db.Column(db.Boolean)

class JamState(db.Model):
    jam_id = db.Column(db.String, primary_key=True)
    host_id = db.Column(db.Integer)
    listeners = db.Column(db.Text)  # JSON


class PlayLog(db.Model):
    __tablename__ = "play_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    song_id = db.Column(db.Integer, db.ForeignKey("song.id"), nullable=False, index=True)

    played_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    listen_duration = db.Column(db.Integer, default=0)  # seconds
    completed = db.Column(db.Boolean, default=False)


class QueueHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    song_id = db.Column(db.Integer, db.ForeignKey("song.id"))
    played_at = db.Column(db.DateTime, default=datetime.utcnow)

class SleepTimer(db.Model):
    user_id = db.Column(db.Integer, primary_key=True)
    end_time = db.Column(db.DateTime)
    fade_out = db.Column(db.Boolean, default=False)

class JamSession(db.Model):
    id = db.Column(db.String(80), primary_key=True)
    host_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    song_id = db.Column(db.Integer, db.ForeignKey("song.id"), nullable=True)
    paused = db.Column(db.Boolean, default=True)
    position = db.Column(db.Float, default=0.0)
    started_at = db.Column(db.DateTime, nullable=True)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)


# =========================================================
# AUTO-CREATE DATABASE TABLES ON STARTUP
# =========================================================
with app.app_context():
    db.create_all()
    print("✅ Database tables created/verified")

# =========================================================
# AUTH ROUTES
# =========================================================

@app.route("/auth/register", methods=["POST"])
def register():
    data = request.json

    pw_hash = bcrypt.generate_password_hash(
        data["password"]
    ).decode()

    user = User(
        username=data["username"],
        email=data["email"],
        password_hash=pw_hash
    )

    try:
        db.session.add(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(
            error="Username or email already exists"
        ), 409

    return jsonify(msg="Registered successfully")


from flask import make_response

@app.route("/auth/login", methods=["POST"])
@limiter.limit("5 per minute; 50 per hour")
def login():
    data = request.json
    user = User.query.filter_by(username=data["username"]).first()

    if not user or not bcrypt.check_password_hash(
        user.password_hash, data["password"]
    ):
        return jsonify(error="Invalid credentials"), 401

    token = create_access_token(identity=str(user.id))

    # Return token in response body. Clients should send it via Authorization header.
    return jsonify(token=token)

# =========================================================
# AUTO-IMPORT LOCAL SONGS (SAFE)
# =========================================================

from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC

def auto_import_songs():
    import re
    
    for file in os.listdir(AUDIO_DIR):
        # MP3 files only
        if not file.lower().endswith(".mp3"):
            continue

        if Song.query.filter_by(audio_file=file).first():
            continue

        file_path = os.path.join(AUDIO_DIR, file)

        # ✅ DEFAULTS (THIS FIXES THE ERROR)
        # Clean up yt-dlp filenames by removing bracketed IDs like [FXovf5dsRTw]
        title = os.path.splitext(file)[0]
        title = re.sub(r'\s*\[[\w-]+\]$', '', title)  # Remove [ID] at end
        artist = "Unknown"
        album = "Unknown Album"
        cover_file = None

        # ---- READ METADATA ----
        try:
            audio = EasyID3(file_path)
            title = audio.get("title", [title])[0]
            artist = audio.get("artist", [artist])[0]
            album = audio.get("album", [album])[0]
            genre = audio.get("genre", ["Unknown"])[0]
        except Exception:
            genre = "Unknown"

        # ---- EXTRACT COVER ----
        try:
            tags = ID3(file_path)
            for tag in tags.values():
                if isinstance(tag, APIC):
                    cover_name = f"{os.path.splitext(file)[0]}.jpg"
                    cover_path = os.path.join(COVER_DIR, cover_name)
                    with open(cover_path, "wb") as img:
                        img.write(tag.data)
                    cover_file = cover_name
                    break
        except Exception:
            pass

        song = Song(
            title=title,
            artist=artist,
            album=album,
            audio_file=file,
            cover_file=cover_file,
            genre=genre,
            uploaded_by=None
        )

        db.session.add(song)

    db.session.commit()
    print("🎵 Auto-import with metadata complete")

def get_player(user_id):
    state = PlaybackState.query.filter_by(user_id=user_id).first()
    if not state:
        state = PlaybackState(
            user_id=user_id,
            original_queue="[]",
            shuffled_queue="[]"
        )
        db.session.add(state)
        db.session.commit()
    return state


def send_range_file(path):
    file_size = os.path.getsize(path)
    range_header = request.headers.get("Range", None)

    if not range_header:
        return send_file(path)

    byte1, byte2 = 0, None
    match = range_header.replace("bytes=", "").split("-")

    byte1 = int(match[0])
    if len(match) > 1 and match[1]:
        byte2 = int(match[1])

    length = file_size - byte1
    if byte2 is not None:
        length = byte2 - byte1 + 1

    with open(path, "rb") as f:
        f.seek(byte1)
        data = f.read(length)

    resp = Response(
        data,
        206,
        mimetype="audio/mpeg",
        content_type="audio/mpeg",
        direct_passthrough=True,
    )

    resp.headers.add(
        "Content-Range",
        f"bytes {byte1}-{byte1 + length - 1}/{file_size}"
    )
    resp.headers.add("Accept-Ranges", "bytes")
    resp.headers.add("Content-Length", str(length))

    return resp


def get_active_queue(state):
    return json.loads(
        state.shuffled_queue if state.shuffle else state.original_queue
    )

# =========================================================
#GENRE BROWSE ENDPOINTS
# =========================================================
@app.route("/browse/genres")
def browse_genres():
    genres = (
        db.session.query(
            Song.genre,
            db.func.count(Song.id),
            db.func.min(Song.cover_file)
        )
        .group_by(Song.genre)
        .all()
    )

    return jsonify([
        {"genre": g, "count": c, "cover": full_url(f"/covers/{cover}") if cover else None}
        for g, c, cover in genres if g
    ])


def get_audio_hash(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

@app.route("/browse/genres/<genre>")
def songs_by_genre(genre):
    songs = Song.query.filter_by(genre=genre).all()
    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None
        }
        for s in songs
    ])

@app.route("/artists", methods=["GET"])
def get_artists():
    # Frontend expects a list of STRINGS (names)
    artists = Artist.query.order_by(Artist.name.asc()).all()
    # If explicit artist table is empty, fallback to distinct songs?
    # But we populated it.
    
    return jsonify([a.name for a in artists])

@app.route("/artists/<path:name>", methods=["GET"])
def get_artist_details(name):
    # Case insensitive search
    # Frontend expects:
    # {
    #   "artist": "Name",
    #   "albums": [{ "album": "Name", "cover": "url" }],
    #   "top_tracks": [ ...songs... ]
    # }

    # 1. Fetch Songs first
    songs = Song.query.filter(func.lower(Song.artist) == func.lower(name)).all()
    
    if not songs:
        # Check if artist exists in Artist table but has no songs?
        artist_entry = Artist.query.filter(func.lower(Artist.name) == func.lower(name)).first()
        if not artist_entry:
             return jsonify(error="Artist not found"), 404
        # If artist exists but no songs, return empty structure
        return jsonify({
            "artist": artist_entry.name,
            "albums": [],
            "top_tracks": []
        })

    # 2. Process Albums
    albums_map = {}
    for s in songs:
        alb_name = s.album or "Unknown Album"
        if alb_name not in albums_map:
            albums_map[alb_name] = s.cover_file # Pick first cover found for album

    albums_list = [
        {
            "album": title, 
            "cover": full_url(f"/covers/{cover}") if cover else None
        }
        for title, cover in albums_map.items()
    ]

    # 3. Format Songs (Top Tracks)
    tracks_list = [
        {
            "id": s.id,
            "title": s.title or "Unknown Title",
            "artist": s.artist or "Unknown Artist",
            "album": s.album or "", 
            "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None, # Use Proxy
            "url": full_url(f"/songs/{s.id}/stream"), # Use Proxy
            "genre": s.genre or "",
            "lyrics": s.lyrics
        }
        for s in songs
    ]

    # Safe artist name
    artist_name = songs[0].artist if (songs and songs[0].artist) else name

    return jsonify({
        "artist": artist_name, 
        "albums": albums_list,
        "top_tracks": tracks_list
    })


@app.route("/songs", methods=["GET"])
def get_songs():
    page = request.args.get("page", 1, type=int)
    limit = request.args.get("limit", 30, type=int)
    sort_by = request.args.get("sort", "random")  # Default to random for variety

    query = Song.query
    if sort_by == "newest":
        query = query.order_by(Song.id.desc())
    elif sort_by == "oldest":
        query = query.order_by(Song.id.asc())
    elif sort_by == "a-z":
        query = query.order_by(Song.title.asc())
    elif sort_by == "random":
        query = query.order_by(func.random())
    
    pagination = query.paginate(page=page, per_page=limit, error_out=False)
    
    data = []
    for s in pagination.items:
        data.append({
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None,
            "audio_url": full_url(f"/songs/{s.id}/stream"),
            "genre": s.genre,
            "lyrics": s.lyrics
        })

    return jsonify({
        "items": data,
        "total": pagination.total,
        "pages": pagination.pages,
        "page": page
    })







# =========================================================
# SEARCH & LANDING
# =========================================================

@app.route("/search", methods=["GET"])
def search_songs():
    q = request.args.get("q", "").strip()
    genre = request.args.get("genre")
    
    if not q and not genre:
        return jsonify(results=[], recommended=[])

    query = Song.query

    # strict filtering by genre if provided
    if genre:
        query = query.filter(Song.genre == genre)

    # fuzzy search logic
    if q:
        # PostgreSQL: ilike is case insensitive. SQLite: like is case insensitive by default for ASCII.
        # We use ilike for Postgres compatibility on Render.
        search_filter = or_(
            Song.title.ilike(f"%{q}%"),
            Song.artist.ilike(f"%{q}%"),
            Song.album.ilike(f"%{q}%"),
            Song.lyrics.ilike(f"%{q}%") # Search in lyrics too!
        )
        query = query.filter(search_filter)

    # Limit results
    results = query.limit(50).all()

    # Format
    data = []
    for s in results:
        data.append({
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None,
            "audio_url": full_url(f"/songs/{s.id}/stream"),
            "genre": s.genre,
            "lyrics": s.lyrics
        })

    return jsonify({
        "results": data,
        "recommended": [] # Todo: implement recommendations based on result
    })


@app.route("/song/<int:song_id>")
def song_landing_page(song_id):
    """
    Landing page for Deep Links.
    If on Mobile -> Try to open App (Intent)
    If on Desktop -> Show Landing Page with Metadata
    """
    song = Song.query.get_or_404(song_id)
    
    # Basic Metadata
    title = song.title
    artist = song.artist
    cover_url = full_url(f"/covers/{song.cover_file}") if song.cover_file else "https://kreewaux.xyz/logo.png"
    
    # Simple HTML Landing Page
    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        
        <!-- Open Graph Data (for Discord/iMessage previews) -->
        <meta property="og:title" content="{title} by {artist}">
        <meta property="og:type" content="music.song">
        <meta property="og:image" content="{cover_url}">
        <meta property="og:description" content="Listen to {title} on Krew.">
        <meta property="og:site_name" content="Krew">
        
        <title>{title} - Krew</title>
        
        <style>
            body {{
                background-color: #0A0A0C;
                color: white;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                height: 100vh;
                margin: 0;
                text-align: center;
            }}
            .cover {{
                width: 200px;
                height: 200px;
                border-radius: 12px;
                box-shadow: 0 8px 32px rgba(0,0,0,0.5);
                margin-bottom: 24px;
                object-fit: cover;
            }}
            h1 {{ margin: 0 0 8px 0; font-size: 24px; }}
            p {{ margin: 0 0 32px 0; color: #B3B3B3; font-size: 18px; }}
            .btn {{
                background: #1DB954;
                color: black;
                text-decoration: none;
                padding: 14px 32px;
                border-radius: 99px;
                font-weight: bold;
                font-size: 16px;
                transition: transform 0.2s;
            }}
            .btn:hover {{ transform: scale(1.05); }}
        </style>
    </head>
    <body>
        <img src="{cover_url}" alt="Cover" class="cover">
        <h1>{title}</h1>
        <p>{artist}</p>
        
        <!-- Deep Link to App -->
        <a href="intent://song/{song_id}#Intent;scheme=https;package=com.krew.music;S.browser_fallback_url=https://play.google.com/store/apps/details?id=com.krew.music;end" class="btn">
            Open in Krew
        </a>
        
        <script>
            // Try to open app automatically
            window.location.href = "intent://api.kreewaux.xyz/song/{song_id}#Intent;scheme=https;package=com.krew.music;end";
        </script>
    </body>
    </html>
    """
    return html


# =========================================================
# Artist Verification Endpoints
# =========================================================

@app.route("/artist/apply", methods=["POST"])
@jwt_required()
def apply_as_artist():
    """Submit an artist verification application"""
    user_id = int(get_jwt_identity())
    
    # Check if user already has artist status or pending application
    user = db.session.get(User, user_id)
    if user and user.is_artist:
        return jsonify(error="You are already a verified artist"), 400
    
    existing_application = ArtistApplication.query.filter_by(
        user_id=user_id, 
        status='pending'
    ).first()
    if existing_application:
        return jsonify(error="You already have a pending application"), 400
    
    # Validate required fields
    data = request.get_json()
    artist_name = data.get('artist_name', '').strip()
    bio = data.get('bio', '').strip()
    
    if not artist_name or not bio:
        return jsonify(error="Artist name and bio are required"), 400
    
    if len(bio) < 50:
        return jsonify(error="Bio must be at least 50 characters"), 400
    
    # Create application
    application = ArtistApplication(
        user_id=user_id,
        artist_name=artist_name,
        bio=bio,
        social_links=data.get('social_links', ''),
        sample_work_url=data.get('sample_work_url', ''),
        status='pending'
    )
    
    db.session.add(application)
    db.session.commit()
    
    return jsonify(
        msg="Artist application submitted successfully",
        application_id=application.id,
        status='pending'
    )


@app.route("/artist/status", methods=["GET"])
@jwt_required()
def artist_status():
    """Get current user's artist status and application status"""
    user_id = int(get_jwt_identity())
    
    user = db.session.get(User, user_id)
    if not user:
        return jsonify(error="User not found"), 404
    
    # Check for pending or recent application
    application = ArtistApplication.query.filter_by(user_id=user_id).order_by(
        ArtistApplication.created_at.desc()
    ).first()
    
    return jsonify(
        is_artist=user.is_artist,
        has_application=application is not None,
        application_status=application.status if application else None,
        application_date=application.created_at.isoformat() if application else None,
        artist_bio=user.artist_bio
    )


@app.route("/admin/artist-applications", methods=["GET"])
@jwt_required()
def get_artist_applications():
    """Get all pending artist applications (admin only)"""
    # TODO: Add admin role check in production
    # For now, any logged-in user can view (you can review manually)
    
    applications = ArtistApplication.query.filter_by(status='pending').order_by(
        ArtistApplication.created_at.desc()
    ).all()
    
    result = []
    for app in applications:
        user = db.session.get(User, app.user_id)
        result.append({
            'id': app.id,
            'user_id': app.user_id,
            'username': user.username if user else 'Unknown',
            'artist_name': app.artist_name,
            'bio': app.bio,
            'social_links': app.social_links,
            'sample_work_url': app.sample_work_url,
            'created_at': app.created_at.isoformat()
        })
    
    return jsonify(applications=result)


@app.route("/admin/artist-applications/<int:app_id>/approve", methods=["POST"])
@jwt_required()
def approve_artist_application(app_id):
    """Approve an artist application (admin only)"""
    # TODO: Add admin role check in production
    admin_id = int(get_jwt_identity())
    
    application = db.session.get(ArtistApplication, app_id)
    if not application:
        return jsonify(error="Application not found"), 404
    
    if application.status != 'pending':
        return jsonify(error="Application is not pending"), 400
    
    # Update application status
    application.status = 'approved'
    application.reviewed_at = datetime.utcnow()
    application.reviewed_by = admin_id
    
    # Update user as artist
    user = db.session.get(User, application.user_id)
    if user:
        user.is_artist = True
        user.artist_application_date = application.created_at
        user.artist_bio = application.bio
    
    db.session.commit()
    
    return jsonify(msg="Artist application approved successfully")


@app.route("/admin/artist-applications/<int:app_id>/reject", methods=["POST"])
@jwt_required()
def reject_artist_application(app_id):
    """Reject an artist application (admin only)"""
    # TODO: Add admin role check in production
    admin_id = int(get_jwt_identity())
    
    application = db.session.get(ArtistApplication, app_id)
    if not application:
        return jsonify(error="Application not found"), 404
    
    if application.status != 'pending':
        return jsonify(error="Application is not pending"), 400
    
    # Update application status
    application.status = 'rejected'
    application.reviewed_at = datetime.utcnow()
    application.reviewed_by = admin_id
    
    db.session.commit()
    
    return jsonify(msg="Artist application rejected")






@app.route("/songs/<int:song_id>/lyrics", methods=["POST"])
@jwt_required()
def update_lyrics(song_id):
    """Update lyrics for a song (crowdsourced from clients)"""
    data = request.json or {}
    lyrics = data.get("lyrics")
    
    if not lyrics:
        return jsonify(error="lyrics required"), 400
        
    song = Song.query.get(song_id)
    if not song:
        return jsonify(error="Song not found"), 404
        
    # Only update if current lyrics are empty or significantly shorter\n    # This acts as a simple heuristic to prevent overwriting good lyrics with bad ones
    current_len = len(song.lyrics) if song.lyrics else 0
    new_len = len(lyrics)
    
    # If we have no lyrics, take them
    # If new lyrics are longer (likely more complete), take them
    if not song.lyrics or new_len > current_len:
        song.lyrics = lyrics
        db.session.commit()
        return jsonify(msg="Lyrics updated")
        
    return jsonify(msg="Lyrics ignored (existing are better)")


@app.route("/songs/<int:song_id>/stream")
def stream_song(song_id):
    song = Song.query.get_or_404(song_id)

    # PROXY R2 AUDIO (Fixes CORS for Visualizer)
    print(f"🎵 PROXY AUDIO: {song.title} ({song.audio_file})") # DEBUG LOG
    url = get_presigned_url(song.audio_file, "audio")
    if url:
        if url.startswith("http"):
            try:
                headers = {}
                range_header = request.headers.get("Range", None)
                if range_header:
                    headers['Range'] = range_header

                req = requests.get(url, headers=headers, stream=True, timeout=10)
                
                if req.status_code not in [200, 206]:
                    print(f"❌ R2 Error for audio {song.audio_file}: {req.status_code}")
                    return jsonify(error="Audio Fetch Failed"), 502

                resp = Response(
                    stream_with_context(req.iter_content(chunk_size=4096)), # Larger chunk for audio
                    content_type=req.headers.get('Content-Type', 'audio/mpeg'),
                    status=req.status_code
                )
                
                # Forward range headers back to the client
                if 'Content-Range' in req.headers:
                    resp.headers['Content-Range'] = req.headers['Content-Range']
                if 'Accept-Ranges' in req.headers:
                    resp.headers['Accept-Ranges'] = req.headers['Accept-Ranges']
                if 'Content-Length' in req.headers:
                    resp.headers['Content-Length'] = req.headers['Content-Length']
                
                # Ensure Accept-Ranges is always present so clients know they can seek
                if 'Accept-Ranges' not in resp.headers:
                    resp.headers['Accept-Ranges'] = 'bytes'

                return resp
            except Exception as e:
                print(f"❌ Proxy Exception for audio {song.audio_file}: {e}")
                return jsonify(error=str(e)), 500

        return redirect(url)

    # Fallback: serve local file
    path = os.path.join(AUDIO_DIR, song.audio_file)
    if not os.path.exists(path):
        return jsonify(error="Audio missing"), 404

    return send_range_file(path)


# =========================================================
# PLAYLISTS
# =========================================================

# 1️⃣ Create playlist
@app.route("/playlists", methods=["POST"])
@jwt_required()
def create_playlist():
    user_id = int(get_jwt_identity())
    data = request.json or {}

    name = (data.get("name") or "").strip()
    if not name:
        return jsonify(error="name is required"), 400

    playlist = Playlist(
        name=name,
        owner_id=user_id
    )
    db.session.add(playlist)
    db.session.commit()

    return jsonify(
        msg="Playlist created",
        id=playlist.id,
        name=playlist.name
    )


# 2️⃣ Get my playlists
@app.route("/playlists", methods=["GET"])
@jwt_required()
def get_playlists():
    user_id = int(get_jwt_identity())
    playlists = Playlist.query.filter_by(owner_id=user_id).all()

    return jsonify([
        {
            "id": p.id, 
            "name": p.name,
            "cover": full_url(f"/covers/{p.cover_file}") if p.cover_file else None
        }
        for p in playlists
    ])


# 3️⃣ Get songs inside a playlist
@app.route("/playlists/<int:pid>", methods=["GET"])
@jwt_required()
def get_playlist_songs(pid):
    user_id = int(get_jwt_identity())
    playlist = Playlist.query.get_or_404(pid)

    if playlist.owner_id != user_id:
        return jsonify(error="Forbidden"), 403

    songs = (
        db.session.query(Song)
        .join(PlaylistSong, Song.id == PlaylistSong.song_id)
        .filter(PlaylistSong.playlist_id == pid)
        .all()
    )

    return jsonify({
        "id": playlist.id,
        "name": playlist.name,
        "cover": get_presigned_url(playlist.cover_file, "covers") if playlist.cover_file else None,
        "songs": [
            {
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
                "audio_url": get_presigned_url(s.audio_file, "audio") if s.audio_file else None,
                "lyrics": s.lyrics
            }
            for s in songs
        ]
    })


# 4️⃣ Add song to playlist
@app.route("/playlists/<int:pid>/add", methods=["POST"])
@jwt_required()
def add_to_playlist(pid):
    user_id = int(get_jwt_identity())
    data = request.json or {}
    if "song_id" not in data:
        return jsonify(error="song_id is required"), 400
    song_id = data["song_id"]

    playlist = Playlist.query.get_or_404(pid)
    if playlist.owner_id != user_id:
        return jsonify(error="Forbidden"), 403

    exists = PlaylistSong.query.filter_by(
        playlist_id=pid,
        song_id=song_id
    ).first()

    if exists:
        return jsonify(msg="Song already in playlist")

    ps = PlaylistSong(
        playlist_id=pid,
        song_id=song_id
    )
    db.session.add(ps)
    db.session.commit()

    return jsonify(msg="Song added to playlist")


# 5️⃣ Remove song from playlist
@app.route("/playlists/<int:pid>/remove", methods=["POST"])
@jwt_required()
def remove_from_playlist(pid):
    user_id = int(get_jwt_identity())
    data = request.json or {}
    if "song_id" not in data:
        return jsonify(error="song_id is required"), 400
    song_id = data["song_id"]

    playlist = Playlist.query.get_or_404(pid)
    if playlist.owner_id != user_id:
        return jsonify(error="Forbidden"), 403

    PlaylistSong.query.filter_by(
        playlist_id=pid,
        song_id=song_id
    ).delete()
    db.session.commit()
    return jsonify(msg="Removed from playlist")

# 6️⃣ Delete playlist
@app.route("/playlists/<int:pid>", methods=["DELETE"])
@jwt_required()
def delete_playlist(pid):
    user_id = int(get_jwt_identity())
    playlist = Playlist.query.get_or_404(pid)

    if playlist.owner_id != user_id:
        return jsonify(error="Forbidden"), 403

    PlaylistSong.query.filter_by(playlist_id=pid).delete()
    db.session.delete(playlist)
    db.session.commit()

    return jsonify(msg="Playlist deleted")

# 7️⃣ Update playlist (Rename)
@app.route("/playlists/<int:playlist_id>", methods=["PUT"])
@jwt_required()
def update_playlist(playlist_id):
    user_id = get_jwt_identity()
    playlist = Playlist.query.filter_by(id=playlist_id, owner_id=user_id).first()
    
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404
        
    data = request.json
    if "name" in data:
        playlist.name = data["name"]
        
    db.session.commit()
    return jsonify({
        "id": playlist.id,
        "name": playlist.name,
        "cover_image": playlist.cover_file
    })

# 8️⃣ Upload Playlist Cover
@app.route("/playlists/<int:playlist_id>/cover", methods=["POST"])
@jwt_required()
def upload_playlist_cover(playlist_id):
    user_id = get_jwt_identity()
    playlist = Playlist.query.filter_by(id=playlist_id, owner_id=user_id).first()
    
    if not playlist:
        return jsonify({"error": "Playlist not found"}), 404
        
    if "cover" not in request.files:
        return jsonify({"error": "No cover file"}), 400
        
    file = request.files["cover"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400
        
    if file:
        ext = os.path.splitext(file.filename)[1]
        filename = f"playlist_{playlist.id}_{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(app.config["UPLOAD_COVER"], filename)
        file.save(filepath)
        
        # Delete old cover if custom
        if playlist.cover_file and playlist.cover_file.startswith("playlist_"):
            try:
                old_path = os.path.join(app.config["UPLOAD_COVER"], playlist.cover_file)
                if os.path.exists(old_path):
                    os.remove(old_path)
            except:
                pass
                
        playlist.cover_file = filename
        db.session.commit()
        
        return jsonify({
            "message": "Cover updated",
            "cover_image": filename
        })

# 9️⃣ Play playlist (loads into player queue)
@app.route("/playlists/<int:pid>/play", methods=["POST"])
@jwt_required()
def play_playlist(pid):
    user_id = int(get_jwt_identity())
    playlist = Playlist.query.get_or_404(pid)

    if playlist.owner_id != user_id:
        return jsonify(error="Forbidden"), 403

    songs = (
        db.session.query(Song.id)
        .join(PlaylistSong, Song.id == PlaylistSong.song_id)
        .filter(PlaylistSong.playlist_id == pid)
        .all()
    )

    song_ids = [s.id for s in songs]

    if not song_ids:
        return jsonify(msg="Playlist is empty")

    state = get_player(user_id)
    state.original_queue = json.dumps(song_ids)
    state.shuffled_queue = json.dumps(song_ids)
    state.current_song_id = song_ids[0]
    state.current_time = 0
    state.is_playing = True

    db.session.commit()

    return jsonify(
        msg="Playlist queued",
        first_song=song_ids[0],
        count=len(song_ids)
    )



# =========================================================
# LIKES / LIBRARY / ALBUMS
# =========================================================







@app.route("/player/shuffle", methods=["POST"])
@jwt_required()
def player_shuffle():
    user_id = int(get_jwt_identity())
    enabled = request.json["enabled"]

    state = get_player(user_id)
    original = json.loads(state.original_queue)

    if enabled and not state.shuffle:
        shuffled = original[:]
        random.shuffle(shuffled)
        state.shuffled_queue = json.dumps(shuffled)

    state.shuffle = enabled
    db.session.commit()
    return jsonify(msg="Shuffle updated", enabled=enabled)


@app.route("/player/next", methods=["POST"])
@jwt_required()
def player_next():
    user_id = int(get_jwt_identity())
    state = get_player(user_id)

    queue = get_active_queue(state)

    if not queue or not state.current_song_id:
        return jsonify(next=None)

    # Repeat one
    if state.repeat == "one":
        song = Song.query.get(state.current_song_id)
        return jsonify(
            id=song.id,
            title=song.title,
            artist=song.artist,
            cover=song.cover_file,
            audio=full_url(f"/songs/{song.id}/stream")
        )

    # -------------------------
    # FIX: Log Play for Stats (Repeat One)
    # -------------------------
    if state.repeat == "one":
         try:
            song = Song.query.get(state.current_song_id)
            play = PlayLog(
                user_id=user_id,
                song_id=song.id,
                played_at=datetime.utcnow()
            )
            db.session.add(play)
            db.session.commit()
         except:
             pass

    try:
        idx = queue.index(state.current_song_id)
    except ValueError:
        idx = -1

    # Normal next
    if idx + 1 < len(queue):
        state.current_song_id = queue[idx + 1]

    # Repeat all
    elif state.repeat == "all":
        state.current_song_id = queue[0]

    # Autoplay (Spotify-style)
    else:
        autoplay_fill(state)
        # Re-fetch queue to see if songs were added
        queue = get_active_queue(state)
        
        if idx + 1 < len(queue):
            state.current_song_id = queue[idx + 1]
        else:
            db.session.commit()
            return jsonify(next=None)

    db.session.commit()
    song = Song.query.get(state.current_song_id)

    # Save to History
    try:
        hist = QueueHistory(user_id=user_id, song_id=song.id)
        db.session.add(hist)
        db.session.commit()
    except:
        pass

    # Discord RPC Update
    discord_service.update(song.title, song.artist)

    # -------------------------
    # FIX: Log Play for Stats (Next)
    # -------------------------
    try:
        play = PlayLog(
            user_id=user_id,
            song_id=song.id,
            played_at=datetime.utcnow()
        )
        db.session.add(play)
        db.session.commit()
    except:
        pass

    return jsonify(
        id=song.id,
        title=song.title,
        artist=song.artist,
        cover=song.cover_file,
        audio=full_url(f"/songs/{song.id}/stream")
    )


@app.route("/player/prev", methods=["POST"])
@jwt_required()
def player_prev():
    user_id = int(get_jwt_identity())
    state = get_player(user_id)
    queue = get_active_queue(state)

    if not queue:
        return jsonify(msg="No queue")

    idx = -1
    if state.current_song_id:
        try:
            idx = queue.index(state.current_song_id)
        except ValueError:
            pass

    prev_id = None
    if idx > 0:
        prev_id = queue[idx - 1]
    elif state.repeat == "all" and queue:
        prev_id = queue[-1]
    
    if prev_id:
        state.current_song_id = prev_id
        db.session.commit()
        
        song = Song.query.get(prev_id)
        if song:
            # Discord RPC Update
            discord_service.update(song.title, song.artist)

            # -------------------------
            # FIX: Log Play for Stats (Prev)
            # -------------------------
            try:
                play = PlayLog(
                    user_id=user_id,
                    song_id=song.id,
                    played_at=datetime.utcnow()
                )
                db.session.add(play)
                db.session.commit()
            except:
                pass
            
            return jsonify({
                "id": song.id,
                "title": song.title,
                "artist": song.artist,
                "cover": full_url(f"/covers/{song.cover_file}") if song.cover_file else None,
                "audio": full_url(f"/audio/{song.audio_file}")
            })
            
    return jsonify(msg="No previous song")


@app.route("/songs/<int:sid>", methods=["GET"])
def get_song_details(sid):
    song = Song.query.get(sid)
    if not song:
        return jsonify(error="Song not found"), 404
        
    return jsonify({
        "id": song.id,
        "title": song.title,
        "artist": song.artist,
        "album": song.album,
        "cover": get_presigned_url(song.cover_file, "covers") if song.cover_file else None,
        "audio": get_presigned_url(song.audio_file, "audio") if song.audio_file else None
    })




@app.route("/player/repeat", methods=["POST"])
@jwt_required()
def player_repeat():
    user_id = int(get_jwt_identity())
    mode = request.json["mode"]  # off | all | one

    state = get_player(user_id)
    state.repeat = mode
    db.session.commit()

    return jsonify(msg="Repeat set", mode=mode)


@app.route("/player/state")
@jwt_required()
def player_state():
    user_id = int(get_jwt_identity())
    state = get_player(user_id)

    song = Song.query.get(state.current_song_id) if state.current_song_id else None

    return jsonify({
        "current": (
            {
                "id": song.id,
                "title": song.title,
                "artist": song.artist,
                "audio": full_url(f"/songs/{song.id}/stream")
            } if song else None
        ),
        "shuffle": state.shuffle,
        "repeat": state.repeat
    })

@app.route("/songs/<int:sid>/liked")
@jwt_required()
def is_liked(sid):
    user_id = int(get_jwt_identity())
    liked = Like.query.filter_by(user_id=user_id, song_id=sid).first()
    return jsonify(liked=bool(liked))


@app.route("/albums")
def albums():
    results = (
        db.session.query(
            Song.album,
            db.func.min(Song.artist).label("artist"),
            db.func.count(Song.id).label("tracks"),
            db.func.min(Song.cover_file).label("cover")
        )
        .filter(Song.album != None, Song.album != "")
        .group_by(Song.album)
        .all()
    )

    return jsonify([
        {
            "album": r.album,
            "artist": r.artist,
            "tracks": r.tracks,
            "cover": r.cover
        }
        for r in results
    ])


@app.route("/albums/<album_name>")
def album_songs(album_name):
    songs = Song.query.filter_by(album=album_name).all()
    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist
        } for s in songs
    ])

@app.route("/artists")
def artists():
    raw = db.session.query(Song.artist).all()
    artist_set = set()
    for (artist_str,) in raw:
        for name in split_artists(artist_str):
            artist_set.add(name)
    return jsonify(sorted(artist_set))


@app.route("/songs/<int:sid>/like", methods=["POST"])
@jwt_required()
def like_song(sid):
    user_id = int(get_jwt_identity())

    exists = Like.query.filter_by(
        user_id=user_id,
        song_id=sid
    ).first()

    if exists:
        return jsonify(msg="Already liked")

    like = Like(user_id=user_id, song_id=sid)
    db.session.add(like)
    db.session.commit()
    return jsonify(msg="Liked")

@app.route("/me/library")
@jwt_required()
def my_library():
    user_id = int(get_jwt_identity())
    
    # Pagination params (optional - for backward compatibility)
    page = request.args.get("page", type=int)
    limit = request.args.get("limit", 50, type=int)

    base_query = (
        db.session.query(Like, Song)
        .join(Song, Like.song_id == Song.id)
        .filter(Like.user_id == user_id)
        .order_by(Like.id.desc())  # recent first
    )
    
    # If pagination requested, return paginated response
    if page is not None:
        total = base_query.count()
        likes = base_query.offset((page - 1) * limit).limit(limit).all()
        
        return jsonify({
            "items": [
                {
                    "id": song.id,
                    "title": song.title,
                    "artist": song.artist,
                    "cover": get_presigned_url(song.cover_file, "covers") if song.cover_file else None,
                    "audio_url": get_presigned_url(song.audio_file, "audio") if song.audio_file else None
                }
                for like, song in likes
            ],
            "total": total,
            "page": page,
            "pages": (total + limit - 1) // limit
        })
    
    # Backward compatible: return all if no pagination
    likes = base_query.all()

    return jsonify([
        {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "cover": get_presigned_url(song.cover_file, "covers") if song.cover_file else None,
            "audio_url": get_presigned_url(song.audio_file, "audio") if song.audio_file else None
        }
        for like, song in likes
    ])

@app.route("/songs/<int:sid>/unlike", methods=["POST"])
@jwt_required()
def unlike_song(sid):
    user_id = int(get_jwt_identity())

    like = Like.query.filter_by(
        user_id=user_id,
        song_id=sid
    ).first()

    if not like:
        return jsonify(msg="Not liked")

    db.session.delete(like)
    db.session.commit()
    return jsonify(msg="Unliked")


# =========================================================
# QUICK WIN FEATURES (DUPLICATES, MERGE, HISTORY, SHUFFLE, TIMER)
# =========================================================

@app.route("/library/duplicates")
@jwt_required()
def find_duplicates():
    user_id = int(get_jwt_identity())
    
    # Find songs with same title OR artist
    duplicates = (
        db.session.query(Song.title, Song.artist, func.count(Song.id))
        .group_by(Song.title, Song.artist)
        .having(func.count(Song.id) > 1)
        .all()
    )
    
    return jsonify([
        {"title": t, "artist": a, "count": c}
        for t, a, c in duplicates
    ])


@app.route("/playlists/merge", methods=["POST"])
@jwt_required()
def merge_playlists():
    user_id = int(get_jwt_identity())
    data = request.json
    playlist_ids = data.get("playlist_ids", [])
    new_name = data.get("name", "Merged Playlist")
    
    if not playlist_ids:
        return jsonify(error="No playlists selected"), 400

    # Create new playlist
    new_playlist = Playlist(name=new_name, owner_id=user_id)
    db.session.add(new_playlist)
    db.session.commit()
    
    # Collect all unique songs
    seen = set()
    for pid in playlist_ids:
        songs = (
            db.session.query(Song.id)
            .join(PlaylistSong)
            .filter(PlaylistSong.playlist_id == pid)
            .all()
        )
        for s in songs:
            if s.id not in seen:
                ps = PlaylistSong(playlist_id=new_playlist.id, song_id=s.id)
                db.session.add(ps)
                seen.add(s.id)
    
    db.session.commit()
    return jsonify({"id": new_playlist.id, "total_songs": len(seen)})


@app.route("/player/history")
@jwt_required()
def queue_history():
    user_id = int(get_jwt_identity())
    
    history = (
        db.session.query(QueueHistory, Song)
        .join(Song)
        .filter(QueueHistory.user_id == user_id)
        .order_by(QueueHistory.played_at.desc())
        .limit(50)
        .all()
    )
    
    return jsonify([
        {
            "id": song.id,
            "title": song.title,
            "artist": song.artist,
            "played_at": h.played_at.isoformat()
        }
        for h, song in history
    ])


@app.route("/player/smart-shuffle", methods=["POST"])
@jwt_required()
def smart_shuffle():
    user_id = int(get_jwt_identity())
    state = get_player(user_id)
    
    queue = json.loads(state.original_queue)
    if not queue:
        return jsonify({"msg": "Queue empty"})

    songs = Song.query.filter(Song.id.in_(queue)).all()
    song_map = {s.id: s for s in songs}
    
    # Group by artist
    by_artist = defaultdict(list)
    for sid in queue:
        if sid in song_map:
            artist = song_map[sid].artist
            by_artist[artist].append(sid)
    
    # Interleave artists
    shuffled = []
    while by_artist:
        keys = list(by_artist.keys())
        random.shuffle(keys) # Randomized interleave order
        
        for artist in keys:
            if by_artist[artist]:
                shuffled.append(by_artist[artist].pop(0))
            
            if not by_artist[artist]:
                del by_artist[artist]
    
    state.shuffled_queue = json.dumps(shuffled)
    state.shuffle = True
    db.session.commit()
    
    return jsonify({"msg": "Smart shuffle enabled", "count": len(shuffled)})


@app.route("/player/sleep-timer", methods=["POST"])
@jwt_required()
def set_sleep_timer():
    user_id = int(get_jwt_identity())
    data = request.json
    
    minutes = int(data.get("minutes", 30))
    if minutes <= 0:
        # Cancel timer
        SleepTimer.query.filter_by(user_id=user_id).delete()
        db.session.commit()
        return jsonify({"active": False})

    end_time = datetime.utcnow() + timedelta(minutes=minutes)
    
    timer = SleepTimer.query.get(user_id)
    if not timer:
        timer = SleepTimer(user_id=user_id)
    
    timer.end_time = end_time
    timer.fade_out = data.get("fade_out", False)
    
    db.session.add(timer)
    db.session.commit()
    
    return jsonify({"end_time": end_time.isoformat()})

@app.route("/player/sleep-timer", methods=["GET"])
@jwt_required()
def get_sleep_timer():
    user_id = int(get_jwt_identity())
    timer = SleepTimer.query.get(user_id)
    
    if not timer or timer.end_time < datetime.utcnow():
        return jsonify({"active": False})
    
    return jsonify({
        "active": True,
        "end_time": timer.end_time.isoformat(),
        "remaining_seconds": (timer.end_time - datetime.utcnow()).total_seconds()
    })



@app.route("/search", methods=["GET"])
def search():
    query = request.args.get("q", "").strip()
    genre_filter = request.args.get("genre")
    
    if not query and not genre_filter:
        return jsonify({"results": [], "top_match": None})

    results = []
    seen_ids = set()

    # Helper to add unique
    def add_songs(songs_list, match_type):
        added_count = 0
        for s in songs_list:
            if s.id not in seen_ids:
                results.append({
                    "id": s.id,
                    "title": s.title,
                    "artist": s.artist,
                    "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
                    "audio": get_presigned_url(s.audio_file, "audio") if s.audio_file else None,
                    "match_type": match_type
                })
                seen_ids.add(s.id)
                added_count += 1
        return added_count

    # 0. Genre Filter (if generic browse)
    if genre_filter:
        genre_matches = Song.query.filter(Song.genre == genre_filter).order_by(func.random()).limit(20).all()
        add_songs(genre_matches, "genre")
        return jsonify({"results": results, "top_match": None})

    # WEIGHTED SEARCH LOGIC
    
    # 1. Exact Title Match (Highest Priority)
    exact_title = Song.query.filter(Song.title.ilike(f"{query}")).all()
    add_songs(exact_title, "exact_title")

    # 2. Exact Artist Match
    exact_artist = Song.query.filter(Song.artist.ilike(f"{query}")).all()
    add_songs(exact_artist, "exact_artist")
    
    # 3. Starts With Title
    starts_title = Song.query.filter(Song.title.ilike(f"{query}%")).limit(5).all()
    add_songs(starts_title, "starts_title")

    # 4. Partial Title
    partial_title = Song.query.filter(Song.title.ilike(f"%{query}%")).limit(10).all()
    add_songs(partial_title, "partial_title")
    
    # 5. Partial Artist
    partial_artist = Song.query.filter(Song.artist.ilike(f"%{query}%")).limit(10).all()
    add_songs(partial_artist, "partial_artist")

    # EXTRACT TOP MATCH
    # The first result in our prioritized list is the "Top Match"
    top_match = results[0] if results else None
    
    # If we have a top match, remove it from the main list so it doesn't duplicate visually
    # OR keep it if frontend handles it. Let's keep distinct.
    main_results = results[1:] if results else []

    return jsonify({
        "top_match": top_match,
        "results": main_results
    })


@app.route("/search/trending", methods=["GET"])
def search_trending():
    # Trending = Most played in last 24h
    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)
    
    trending_raw = (
        db.session.query(Song, func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.played_at >= yesterday)
        .group_by(Song.id)
        .order_by(desc("plays"))
        .limit(10)
        .all()
    )
    
    # Fallback to random popular if no data
    if not trending_raw:
        trending = Song.query.order_by(func.random()).limit(6).all()
    else:
        trending = [s for s, _ in trending_raw]

    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None
        }
        for s in trending
    ])


@app.route("/artists/<artist_name>")
def artist_page(artist_name):
    # Search for songs where artist_name is one of the split names
    query_pattern = f"%{artist_name}%"
    
    # We use a broader query first, then filter in python for accuracy
    potential_songs = Song.query.filter(Song.artist.like(query_pattern)).all()
    
    matching_songs = []
    for s in potential_songs:
        if artist_name in split_artists(s.artist):
            matching_songs.append(s)

    if not matching_songs:
        return jsonify(error="Artist not found"), 404

    # Group into albums
    album_map = {}
    for s in matching_songs:
        if s.album and s.album not in album_map:
            album_map[s.album] = s.cover_file

    # Top tracks (filtered from matching_songs)
    song_ids = [s.id for s in matching_songs]
    top_tracks_raw = (
        db.session.query(Song, db.func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(Song.id.in_(song_ids))
        .group_by(Song.id)
        .order_by(db.func.count(PlayLog.id).desc())
        .limit(10)
        .all()
    )

    return jsonify({
        "artist": artist_name,
        "albums": [
            {"album": name, "cover": cover}
            for name, cover in album_map.items()
        ],
        "top_tracks": [
            {"id": s.id, "title": s.title, "artist": s.artist, "cover": s.cover_file}
            for s, _ in top_tracks_raw
        ]
    })

# =========================================================
# QUEUE
# =========================================================

@app.route("/player/queue/modify", methods=["POST"])
@jwt_required()
def modify_queue():
    user_id = int(get_jwt_identity())
    state = get_player(user_id)

    data = request.json or {}
    action = data.get("action")
    if action not in {"remove", "play_next", "clear"}:
        return jsonify(error="invalid action"), 400

    queue = json.loads(state.original_queue)

    # REMOVE songs
    if action == "remove":
        remove_ids = set(data.get("song_ids", []))
        queue = [sid for sid in queue if sid not in remove_ids]

    # PLAY NEXT
    elif action == "play_next":
        song_id = data["song_id"]
        if song_id in queue:
            queue.remove(song_id)

        try:
            idx = queue.index(state.current_song_id)
            queue.insert(idx + 1, song_id)
        except ValueError:
            queue.insert(0, song_id)

    # CLEAR QUEUE
    elif action == "clear":
        queue = []
        state.current_song_id = None

    state.original_queue = json.dumps(queue)

    # keep shuffle in sync
    if state.shuffle:
        shuffled = queue[:]
        random.shuffle(shuffled)
        state.shuffled_queue = json.dumps(shuffled)
    else:
        state.shuffled_queue = json.dumps(queue)

    db.session.commit()
    return jsonify(msg="Queue updated", queue=queue)

@app.route("/player/queue")
@jwt_required()
def player_queue():
    user_id = int(get_jwt_identity())
    state = get_player(user_id)

    queue = get_active_queue(state)
    songs = {s.id: s for s in Song.query.filter(Song.id.in_(queue)).all()}

    return jsonify({
    "current_song": state.current_song_id,
    "queue": [
        {
            "id": songs[sid].id,
            "title": songs[sid].title,
            "artist": songs[sid].artist,
            "cover": full_url(f"/covers/{songs[sid].cover_file}") if songs[sid].cover_file else None
        }
        for sid in queue if sid in songs
    ]
})



def autoplay_fill(state):
    last_song = Song.query.get(state.current_song_id)
    if not last_song:
        return

    queue = json.loads(state.original_queue)
    existing_ids = set(queue)

    # Fetch last 50 played songs to avoid repetition
    recent_plays = (
        PlayLog.query
        .filter_by(user_id=state.user_id)
        .order_by(PlayLog.played_at.desc())
        .limit(50)
        .all()
    )
    for p in recent_plays:
        existing_ids.add(p.song_id)

    # 1.5 Explicitly exclude current song (critical for next button)
    if state.current_song_id:
        existing_ids.add(state.current_song_id)
    
    # 1. Try: Similar Artist (Smart Match)
    # Split "Pritam, Arijit Singh" -> ["Pritam", "Arijit Singh"]
    import re
    artists = [a.strip() for a in re.split(r'[,&]|\sfeat\.|\sft\.', last_song.artist, flags=re.IGNORECASE) if a.strip()]
    
    # Create fuzzy filters for each artist part
    artist_filters = [Song.artist.ilike(f"%{a}%") for a in artists]
    
    # Prioritize: Songs by same artist(s), excluding current
    related = (
        Song.query
        .filter(or_(*artist_filters))
        .filter(Song.id.notin_(existing_ids))
        .order_by(func.random())
        .limit(10) # Fetched more
        .all()
    )

    # 1.5 Try: BPM Match (Vibe) - if current song has BPM
    if len(related) < 10 and last_song.bpm:
        # +/- 10 BPM range
        bpm_range = 10
        bpm_songs = (
            Song.query
            .filter(
                Song.bpm.between(last_song.bpm - bpm_range, last_song.bpm + bpm_range),
                Song.id.notin_(existing_ids),
                ~Song.id.in_([s.id for s in related])
            )
            .order_by(func.random())
            .limit(10 - len(related))
            .all()
        )
        related.extend(bpm_songs)

    # 2. Try: Same Genre (if shortage)
    valid_genre = last_song.genre and last_song.genre.lower() not in ['unknown', 'import', 'other', 'single', 'undefined']
    
    if len(related) < 10 and valid_genre:
        genre_songs = (
            Song.query
            .filter(
                Song.genre == last_song.genre,
                Song.id.notin_(existing_ids),
                ~Song.id.in_([s.id for s in related])
            )
            .order_by(func.random())
            .limit(10 - len(related))
            .all()
        )
        related.extend(genre_songs)

    # 3. Fallback: Completely Random (excluding history)
    if len(related) < 5:
        random_songs = (
            Song.query
            .filter(Song.id.notin_(existing_ids))
            .filter(~Song.id.in_([s.id for s in related]))
            .order_by(func.random())
            .limit(10 - len(related))
            .all()
        )
        related.extend(random_songs)

    if not related:
        return

    # Append new songs
    new_ids = [s.id for s in related]
    queue.extend(new_ids)

    state.original_queue = json.dumps(queue)

    # 🔥 CRITICAL: keep shuffle in sync
    if state.shuffle:
        shuffled = json.loads(state.shuffled_queue) if state.shuffled_queue else []
        # Add new songs to shuffled queue too (randomly inserted or appended)
        # For simplicity, just append and shuffle the new chunk? 
        # Or just append to end of shuffled.
        shuffled.extend(new_ids)
        # Re-shuffle only the new part? No, users expect random. 
        # But we don't want to reshuffle the *played* history.
        # Just appending is fine for "autoplay" feel.
        state.shuffled_queue = json.dumps(shuffled)

@app.route("/player/queue/add", methods=["POST"])
@jwt_required()
def player_queue_add():
    user_id = int(get_jwt_identity())
    data = request.json or {}
    if "song_id" not in data:
        return jsonify(error="song_id is required"), 400
    song_id = data["song_id"]

    state = get_player(user_id)
    queue = json.loads(state.original_queue)

    queue.append(song_id)
    state.original_queue = json.dumps(queue)

    if state.shuffle:
        shuffled = queue[:]
        random.shuffle(shuffled)
        state.shuffled_queue = json.dumps(shuffled)

    db.session.commit()
@app.route("/player/queue/modify", methods=["POST"])
@jwt_required()
def player_queue_modify():
    user_id = int(get_jwt_identity())
    data = request.json or {}
    action = data.get("action")
    
    state = get_player(user_id)
    if not state.original_queue:
        return jsonify(msg="Queue empty or error"), 400
        
    queue = json.loads(state.original_queue)
    
    if action == "remove":
        # Remove specific song IDs
        to_remove = set(data.get("song_ids", []))
        queue = [sid for sid in queue if sid not in to_remove]
        
    elif action == "play_next":
        # Move song to front (after current)
        song_id = data.get("song_id")
        if song_id:
             # If already in queue, remove it
             if song_id in queue:
                 queue.remove(song_id)
             # Insert at front (index 0)
             queue.insert(0, song_id)
             
    elif action == "clear":
        queue = []
        
    elif action == "reorder":
        # Set queue to exact new order
        new_order = data.get("song_ids", [])
        if new_order:
            # Validate: ensure we only reorder existing songs to avoid corruption?
            # Or trust client? Validating is safer.
            current_set = set(queue)
            valid_new_order = [sid for sid in new_order if sid in current_set]
            
            # If client sends partial list, we might lose songs. 
            # Strategy: Take new order, append any remaining songs that were in queue but not in new order
            # (unless intent is to replace? "reorder" usually implies just shuffling existing)
            
            new_set = set(valid_new_order)
            leftovers = [sid for sid in queue if sid not in new_set]
            
            queue = valid_new_order + leftovers
            
    else:
        return jsonify(error="Invalid action"), 400

    state.original_queue = json.dumps(queue)
    
    # Sync shuffle if needed (reset shuffle to match or try to preserve?)
    # For now, if modified, let's just reset shuffled queue or re-shuffle
    if state.shuffle:
         shuffled = queue[:]
         random.shuffle(shuffled)
         state.shuffled_queue = json.dumps(shuffled)

    db.session.commit()
    return jsonify(msg="Queue updated", queue=queue)



@app.route("/me/recent", methods=["GET"])
@jwt_required()
def get_recent_tracks():
    user_id = int(get_jwt_identity())
    # Get latest 50 plays to extract unique recent songs
    logs = PlayLog.query.filter_by(user_id=user_id).order_by(PlayLog.played_at.desc()).limit(50).all()

    # Batch fetch all songs to avoid N+1 query
    song_ids = [log.song_id for log in logs]
    songs = {s.id: s for s in Song.query.filter(Song.id.in_(song_ids)).all()}
    
    # Return unique songs in order of play
    unique_songs = []
    seen = set()
    for log in logs:
        if log.song_id not in seen and log.song_id in songs:
            s = songs[log.song_id]
            unique_songs.append({
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None,
                "audio": full_url(f"/songs/{s.id}/stream")
            })
            seen.add(log.song_id)
            
    return jsonify(unique_songs)

@app.route("/me/streak")
@jwt_required()
def get_user_streak():
    user_id = int(get_jwt_identity())
    
    # 1. Calculate Streak (Consecutive days)
    # Get all unique dates played sorted desc
    dates_raw = (
        db.session.query(func.date(PlayLog.played_at))
        .filter(PlayLog.user_id == user_id)
        .group_by(func.date(PlayLog.played_at))
        .order_by(desc(func.date(PlayLog.played_at)))
        .all()
    )
    
    # Convert to set of strings/dates
    dates = [d[0] for d in dates_raw] # query returns list of tuples
    
    streak = 0
    today = datetime.utcnow().date()
    yesterday = today - timedelta(days=1)
    
    # Logic: If played today, streak starts from today. If not played today but played yesterday, starts yesterday.
    # If neither, streak is 0.
    
    if not dates:
        streak = 0
    else:
        # Check if most recent is today or yesterday
        last_play = dates[0] # date object or string? SQLAlchemy func.date usually returns date
        if isinstance(last_play, str):
            last_play = datetime.strptime(last_play, "%Y-%m-%d").date()
            
        if last_play == today:
            streak = 1
            current_check = yesterday
            idx = 1
        elif last_play == yesterday:
            streak = 1
            current_check = yesterday - timedelta(days=1)
            idx = 1
        else:
            streak = 0
            current_check = None # Break
            
        # Count backwards
        if streak > 0:
            while idx < len(dates):
                prev_date = dates[idx]
                if isinstance(prev_date, str):
                     prev_date = datetime.strptime(prev_date, "%Y-%m-%d").date()
                     
                if prev_date == current_check:
                    streak += 1
                    current_check = current_check - timedelta(days=1)
                elif prev_date > current_check:
                    # Duplicate date (shouldn't happen due to group_by)
                    pass 
                else:
                    # Gap found
                    break
                idx += 1

    # 2. Minutes Listened Today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_query = (
        db.session.query(func.sum(PlayLog.listen_duration))
        .filter(PlayLog.user_id == user_id, PlayLog.played_at >= today_start)
        .scalar()
    )
    minutes_today = int((minutes_query or 0) / 60)
    
    # 3. Top Genre (Last 7 Days)
    week_start = today_start - timedelta(days=7)
    top_genre_raw = (
        db.session.query(Song.genre, func.count(PlayLog.id).label("count"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id, PlayLog.played_at >= week_start)
        .group_by(Song.genre)
        .order_by(desc("count"))
        .first()
    )
    top_genre = top_genre_raw[0] if top_genre_raw else "Unknown"
    
    return jsonify({
        "streak_days": streak,
        "minutes_today": minutes_today,
        "top_genre": top_genre
    })

@app.route("/songs/<int:sid>/played", methods=["POST"])
@jwt_required()
def log_play_duration(sid):
    user_id = int(get_jwt_identity())
    data = request.json or {}
    duration = data.get("duration", 0) # in seconds
    
    # Check for recent log (created by /player/play within last 20 mins) 
    # to update duration instead of duplicate
    cutoff = datetime.utcnow() - timedelta(minutes=20)
    
    recent_log = (
        PlayLog.query
        .filter(PlayLog.user_id == user_id, PlayLog.song_id == sid, PlayLog.played_at >= cutoff)
        .order_by(PlayLog.played_at.desc())
        .first()
    )
    
    if recent_log:
        # Update existing
        # Aggregate duration? If user played same song twice?
        # Ideally, valid duration replaces 0. If > 0, maybe add?
        if recent_log.listen_duration == 0:
             recent_log.listen_duration = duration
        else:
            # Create NEW log if previous one already has duration (implies handled)
             new_log = PlayLog(user_id=user_id, song_id=sid, listen_duration=duration)
             db.session.add(new_log)
    else:
        # No recent log, create new
        new_log = PlayLog(user_id=user_id, song_id=sid, listen_duration=duration)
        db.session.add(new_log)
        
    db.session.commit()
    return jsonify(msg="Logged", duration=duration)


# =========================================================
# RADIO   SONG-RADIO   ARTIST-RADIO  ALBUM-RADIO / BECAUSE YOU LISTENED 
# ========================================================
@app.route("/radio/song/<int:sid>")
def song_radio(sid):
    song = Song.query.get_or_404(sid)
    
    # Prioritize same artist, then same genre
    same_artist = (
        Song.query
        .filter(Song.artist == song.artist, Song.id != sid)
        .order_by(db.func.random())
        .limit(15)
        .all()
    )
    
    same_genre = (
        Song.query
        .filter(
            Song.genre == song.genre,
            Song.artist != song.artist,
            Song.id != sid
        )
        .order_by(db.func.random())
        .limit(5)
        .all()
    )
    
    songs = same_artist + same_genre
    
    return jsonify([
        {
            "id": s.id, 
            "title": s.title, 
            "artist": s.artist, 
            "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
            "audio_url": get_presigned_url(s.audio_file, "audio") if s.audio_file else None
        }
        for s in songs
    ])
@app.route("/radio/artist/<artist>")
def artist_radio(artist):
    query_pattern = f"%{artist}%"
    potential_songs = Song.query.filter(Song.artist.like(query_pattern)).all()
    
    matching_songs = []
    for s in potential_songs:
        if artist in split_artists(s.artist):
            matching_songs.append(s)
    
    # Shuffle and limit
    random.shuffle(matching_songs)
    songs = matching_songs[:30]

    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
            "audio_url": get_presigned_url(s.audio_file, "audio") if s.audio_file else None
        }
        for s in songs
    ])
@app.route("/radio/album/<album>")
def album_radio(album):
    songs = (
        Song.query
        .filter(Song.album == album)
        .order_by(db.func.random())
        .all()
    )

    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
            "audio_url": get_presigned_url(s.audio_file, "audio") if s.audio_file else None
        }
        for s in songs
    ])
@app.route("/because/<int:sid>")
def because_you_listened(sid):
    song = Song.query.get_or_404(sid)

    results = []

    # ----------------------------
    # 1️⃣ SAME ARTIST (PRIMARY)
    # ----------------------------
    if song.artist:
        artist_matches = (
            Song.query
            .filter(
                Song.artist.ilike(f"%{song.artist.split('/')[0].strip()}%"),
                Song.id != sid
            )
            .limit(6)
            .all()
        )
        results.extend(artist_matches)

    # ----------------------------
    # 2️⃣ SAME ALBUM (FALLBACK)
    # ----------------------------
    if song.album:
        album_matches = (
            Song.query
            .filter(
                Song.album == song.album,
                Song.id != sid,
                ~Song.id.in_([s.id for s in results])
            )
            .limit(4)
            .all()
        )
        results.extend(album_matches)

    # ----------------------------
    # 3️⃣ SAME GENRE (FINAL FALLBACK)
    # ----------------------------
    if song.genre and len(results) < 10:
        genre_matches = (
            Song.query
            .filter(
                Song.genre == song.genre,
                Song.id != sid,
                ~Song.id.in_([s.id for s in results])
            )
            .order_by(db.func.random())
            .limit(10 - len(results))
            .all()
        )
        results.extend(genre_matches)

    # ----------------------------
    # 4️⃣ HARD FALLBACK (ANY SONG)
    # ----------------------------
    if len(results) < 5:
        random_fill = (
            Song.query
            .filter(Song.id != sid)
            .order_by(db.func.random())
            .limit(5)
            .all()
        )
        results.extend(random_fill)

    # ----------------------------
    # 5️⃣ FINAL RESPONSE
    # ----------------------------
    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "album": s.album,
            "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
            "audio_url": get_presigned_url(s.audio_file, "audio") if s.audio_file else None
        }
        for s in dict.fromkeys(results)
    ])



# =========================================================
# JAM (WEBSOCKETS)
# =========================================================



# In-memory jam state
# Changed: introduce jam_state as the single source of truth for Jam playback
jam_state = {}          # { jam_id: { song_id, started_at, paused, position, last_activity } }
jam_listeners = {}      # { jam_id: { user_id: username } }
jam_skip_votes = {}     # { jam_id: set(user_ids) }
jam_hosts = {}          # { jam_id: host_user_id }

# Track socket -> jam association for cleanup and host handoff on disconnect
import threading
jam_lock = threading.RLock()
jam_sockets = {}        # { sid: { jam_id, user_id } }

# MEMORY LEAK PREVENTION: Clean up inactive jam sessions
JAM_INACTIVE_TIMEOUT = 7200  # 2 hours in seconds

def cleanup_inactive_jams():
    """Remove jam sessions that have been inactive for JAM_INACTIVE_TIMEOUT seconds."""
    now = time.time()
    with jam_lock:
        inactive_jams = []
        for jam_id, state in jam_state.items():
            last_activity = state.get("last_activity", 0)
            if now - last_activity > JAM_INACTIVE_TIMEOUT:
                inactive_jams.append(jam_id)
        
        for jam_id in inactive_jams:
            jam_state.pop(jam_id, None)
            jam_listeners.pop(jam_id, None)
            jam_skip_votes.pop(jam_id, None)
            jam_hosts.pop(jam_id, None)
            print(f"🧹 Cleaned up inactive jam: {jam_id}")
        
        if inactive_jams:
            print(f"🧹 Cleaned up {len(inactive_jams)} inactive jams. Active: {len(jam_state)}")
            
            # Identify DB jams explicitly marked as old or just rely on memory cleanup? 
            # For strictness, let's delete from DB too if they are super old (e.g. 24h) 
            # to prevent infinite DB growth.
            try:
                expiration = datetime.utcnow() - timedelta(hours=24)
                JamSession.query.filter(JamSession.last_active < expiration).delete()
                db.session.commit()
            except Exception as e:
                print(f"Failed to clean old DB jams: {e}")

# Schedule periodic cleanup (runs every 30 minutes)
def start_jam_cleanup_scheduler():
    def run_cleanup():
        while True:
            time.sleep(1800)  # 30 minutes
            cleanup_inactive_jams()
    
    cleanup_thread = threading.Thread(target=run_cleanup, daemon=True)
    cleanup_thread.start()
    print("🧹 Jam cleanup scheduler started")

# Start cleanup on app load
start_jam_cleanup_scheduler()



# Helper to broadcast full state
def broadcast_jam_state(jam_id, event="jam:sync"):
    state = jam_state.get(jam_id)
    if not state:
        return

    # Calculate server time for drift correction
    # Note: javascript Date.now() is ms, time.time() is seconds
    server_time = time.time()

    payload = {
        "song_id": state["song_id"],
        "paused": state["paused"],
        "started_at": state["started_at"].isoformat() if state["started_at"] else None,
        "position": state["position"], 
        "server_time": server_time
    }

    emit(event, payload, room=f"jam:{jam_id}")

def socket_user_id(token):
    try:
        decoded = decode_token(token, csrf_value=None)
        return int(decoded["sub"])
    except Exception:
        return None


@socketio.on("jam:join")
def jam_join(data):
    user_id = socket_user_id(data.get("token"))
    jam_id = data.get("jam_id")
    print(f"DEBUG: jam:join request - User: {user_id}, Jam: {jam_id}")

    if not user_id or not jam_id:
        print("DEBUG: jam:join failed - Invalid user or jam ID")
        return

    room = f"jam:{jam_id}"
    join_room(room)

    with jam_lock:
        jam_listeners.setdefault(jam_id, {})
        jam_listeners[jam_id][user_id] = f"user_{user_id}"
        # Bind this socket to jam for proper cleanup on disconnect
        jam_sockets[request.sid] = {"jam_id": jam_id, "user_id": user_id}

    # 👑 FIRST USER = HOST
    if jam_id not in jam_hosts:
        
        # TRY LOAD FROM DB
        db_jam = JamSession.query.get(jam_id)
        if db_jam:
             jam_hosts[jam_id] = db_jam.host_id
             jam_state[jam_id] = {
                "song_id": db_jam.song_id,
                "started_at": db_jam.started_at,
                "paused": db_jam.paused,
                "position": db_jam.position,
                "last_activity": time.time()
             }
             print(f"📥 Loaded Jam {jam_id} from DB")
        else:
            # CREATE NEW
            jam_hosts[jam_id] = user_id
            jam_state[jam_id] = {
                "song_id": None,
                "started_at": None,
                "paused": True,
                "position": 0,
                "last_activity": time.time()
            }
            
            # SAVE TO DB
            try:
                new_jam = JamSession(
                    id=jam_id,
                    host_id=user_id,
                    last_active=datetime.utcnow()
                )
                db.session.add(new_jam)
                db.session.commit()
            except Exception as e:
                print(f"Failed to create Jam DB: {e}")

        emit("jam:host", {"user_id": jam_hosts[jam_id]}, room=room)

    # 🔁 SEND CURRENT STATE TO JOINER (only to the joining socket)
    state = jam_state.get(jam_id)
    if not state:
        # Safety: initialize if missing
        jam_state[jam_id] = {
            "song_id": None,
            "started_at": None,
            "paused": True,
            "position": 0,
            "last_activity": time.time()
        }
        state = jam_state[jam_id]

    emit(
        "jam:sync",
        {
            "song_id": state["song_id"],
            "paused": state["paused"],
            "position": get_current_position(jam_id)
        },
        to=request.sid
    )

    emit("jam:listeners", list(jam_listeners[jam_id].values()), room=room)

@socketio.on("jam:play")
def jam_play(data):
    user_id = socket_user_id(data.get("token"))
    jam_id = data.get("jam_id")
    song_id = data.get("song_id")
    # Use provided position, default to 0.0 if missing
    position = float(data.get("position", 0.0))

    print(f"DEBUG: jam:play request - User: {user_id}, Jam: {jam_id}, Song: {song_id}")

    # Anyone in the jam can control playback (peer-to-peer model)
    if not user_id or jam_id not in jam_listeners:
        print(f"DEBUG: jam:play ignored - User {user_id} not in jam {jam_id}")
        return

    if not song_id:
        return  # Safety: ignore invalid song_id

    # Changed: update jam_state ONLY; no DB writes, jam_state is authority
    jam_state.setdefault(jam_id, {})
    jam_state[jam_id] = {
        "song_id": song_id,
        "started_at": datetime.utcnow(),
        "paused": False,
        "position": position
    }
    
    # DB SYNC
    try:
        jam_db = JamSession.query.get(jam_id)
        if jam_db:
            jam_db.song_id = song_id
            jam_db.started_at = datetime.utcnow()
            jam_db.paused = False
            jam_db.position = position
            jam_db.last_active = datetime.utcnow()
            db.session.commit()
    except Exception as e:
        print(f"Jam DB Sync Error (Play): {e}")

    # Broadcast to all listeners
    broadcast_jam_state(jam_id, "jam:play")

@socketio.on("jam:pause")
def jam_pause(data):
    user_id = socket_user_id(data.get("token"))
    jam_id = data.get("jam_id")

    # Anyone in the jam can control playback (peer-to-peer model)
    if not user_id or jam_id not in jam_listeners:
        return

    state = jam_state.get(jam_id)
    if not state:
        return  # Safety

    # Use client provided position if available, else calc
    pos = float(data.get("position", get_current_position(jam_id)))

    # Changed: update jam_state ONLY
    state["paused"] = True
    state["position"] = pos
    state["started_at"] = None  # freeze clock

    # DB SYNC
    try:
        jam_db = JamSession.query.get(jam_id)
        if jam_db:
            jam_db.paused = True
            jam_db.position = pos
            jam_db.started_at = None
            jam_db.last_active = datetime.utcnow()
            db.session.commit()
    except Exception as e:
        print(f"Jam DB Sync Error (Pause): {e}")

    broadcast_jam_state(jam_id, "jam:pause")
@socketio.on("jam:seek")
def jam_seek(data):
    user_id = socket_user_id(data.get("token"))
    jam_id = data.get("jam_id")
    position = float(data.get("position", 0.0))

    # Anyone in the jam can control playback (peer-to-peer model)
    if not user_id or jam_id not in jam_listeners:
        return

    state = jam_state.get(jam_id)
    if not state:
        return  # Safety

    # Changed: update position only, preserve paused state
    state["position"] = position
    state["started_at"] = datetime.utcnow() if not state.get("paused") else None

    # DB SYNC
    try:
        jam_db = JamSession.query.get(jam_id)
        if jam_db:
            jam_db.position = position
            if not state.get("paused"):
                jam_db.started_at = datetime.utcnow()
            jam_db.last_active = datetime.utcnow()
            db.session.commit()
    except Exception as e:
        print(f"Jam DB Sync Error (Seek): {e}")

    broadcast_jam_state(jam_id, "jam:seek")


@socketio.on("jam:message")
def jam_message(data):
    """
    data = { jam_id, token, message }
    """
    user_id = socket_user_id(data.get("token"))
    jam_id = data.get("jam_id")

    if not user_id or not jam_id:
        return  # ❌ reject invalid users

    emit(
        "jam:message",
        {
            "user": f"user_{user_id}",
            "message": data.get("message", "")
        },
        room=f"jam:{jam_id}"
    )


@socketio.on("jam:vote_skip")
def jam_vote_skip(data):
    """
    data = { jam_id, token }
    """
    user_id = socket_user_id(data.get("token"))
    jam_id = data.get("jam_id")

    if not user_id or jam_id not in jam_listeners:
        return  # ❌ reject invalid users / jams

    listeners = jam_listeners[jam_id]
    jam_skip_votes.setdefault(jam_id, set())

    # Add vote
    jam_skip_votes[jam_id].add(user_id)

    listener_count = len(listeners)

    # 🔢 Vote rule
    if listener_count <= 2:
        required = listener_count
    else:
        required = math.ceil(listener_count * 0.6)

    # 🚨 Votes reached → next song (Spotify Jam behavior)
    if len(jam_skip_votes[jam_id]) >= required:
        jam_skip_votes[jam_id].clear()

        host_id = jam_hosts.get(jam_id)
        if not host_id:
            return

        # Changed: READ-ONLY DB usage to get host queue; jam_state is authority for current song
        state_row = PlaybackState.query.filter_by(user_id=host_id).first()
        if not state_row:
            return  # no queue to advance

        queue_json = state_row.shuffled_queue if state_row.shuffle else state_row.original_queue
        try:
            queue = json.loads(queue_json or "[]")
        except Exception:
            queue = []

        if not queue:
            return

        current_song_id = (jam_state.get(jam_id) or {}).get("song_id")
        next_song_id = None

        if current_song_id in queue:
            try:
                idx = queue.index(current_song_id)
                if idx + 1 < len(queue):
                    next_song_id = queue[idx + 1]
                else:
                    # loop to start if at end
                    next_song_id = queue[0] if queue else None
            except ValueError:
                next_song_id = queue[0]
        else:
            next_song_id = queue[0]

        if not next_song_id:
            return

        # Update jam_state ONLY and broadcast jam:play
        jam_state.setdefault(jam_id, {})
        jam_state[jam_id] = {
            "song_id": next_song_id,
            "started_at": datetime.utcnow(),
            "paused": False,
            "position": 0.0
        }
        
        # DB SYNC (Vote Skip -> Next Song)
        try:
            jam_db = JamSession.query.get(jam_id)
            if jam_db:
                jam_db.song_id = next_song_id
                jam_db.started_at = datetime.utcnow()
                jam_db.paused = False
                jam_db.position = 0.0
                jam_db.last_active = datetime.utcnow()
                db.session.commit()
        except: pass

        broadcast_jam_state(jam_id, "jam:play")

    # 🗳 Still voting
    else:
        emit(
            "jam:skip_votes",
            {
                "votes": len(jam_skip_votes[jam_id]),
                "required": required
            },
            room=f"jam:{jam_id}"
        )

# Handle socket disconnects: cleanup listeners, votes, and host handoff
@socketio.on("disconnect")
def on_disconnect():
    sid = request.sid
    info = jam_sockets.pop(sid, None)
    if not info:
        return
    jam_id = info["jam_id"]
    user_id = info["user_id"]

    listeners = jam_listeners.get(jam_id, {})
    if user_id in listeners:
        listeners.pop(user_id, None)

    votes = jam_skip_votes.get(jam_id)
    if votes and user_id in votes:
        votes.discard(user_id)

    # If host left, transfer host or cleanup jam
    if jam_hosts.get(jam_id) == user_id:
        remaining_ids = list(listeners.keys())
        if remaining_ids:
            new_host_id = remaining_ids[0]
            jam_hosts[jam_id] = new_host_id
            emit("jam:host", {"user_id": new_host_id}, room=f"jam:{jam_id}")
            
            # Update Host in DB
            try:
                jam_db = JamSession.query.get(jam_id)
                if jam_db:
                    jam_db.host_id = new_host_id
                    db.session.commit()
            except: pass
        else:
            # No listeners remain; cleanup jam state
            jam_hosts.pop(jam_id, None)
            jam_state.pop(jam_id, None)
            jam_listeners.pop(jam_id, None)
            jam_skip_votes.pop(jam_id, None)

    # Broadcast updated listeners list
    emit("jam:listeners", list(jam_listeners.get(jam_id, {}).values()), room=f"jam:{jam_id}")


# =========================================================
# ANALYTICS
# =========================================================

@app.route("/songs/<int:sid>/played", methods=["POST"])
@jwt_required()
def log_play(sid):
    data = request.json or {}
    duration = int(data.get("duration") or 0)
    
    play = PlayLog(
        user_id=int(get_jwt_identity()),
        song_id=sid,
        listen_duration=duration
    )
    db.session.add(play)
    db.session.commit()
    return jsonify(msg="Play logged", duration=duration)






# =========================================================
# RECOMMENDATIONS (BASIC-ADVANCE(MID))
# =========================================================

@app.route("/recommendations")
@jwt_required()
def recommendations():
    user_id = int(get_jwt_identity())

    top_artists = (
        db.session.query(Song.artist)
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .group_by(Song.artist)
        .order_by(db.func.count(PlayLog.id).desc())
        .limit(3)
        .all()
    )

    artist_names = [a[0] for a in top_artists]
    played_ids = [p.song_id for p in PlayLog.query.filter_by(user_id=user_id)]

    # If no history, fallback to popular songs globally
    base_query = Song.query
    if artist_names:
        base_query = base_query.filter(Song.artist.in_(artist_names))

    songs = (
        base_query
        .filter(Song.id.notin_(played_ids))
        .outerjoin(PlayLog, PlayLog.song_id == Song.id)
        .group_by(Song.id)
        .order_by(db.func.count(PlayLog.id).desc(), Song.id.desc())
        .limit(20)
        .all()
    )

    return jsonify([
        {
            "id": s.id, 
            "title": s.title, 
            "artist": s.artist, 
            "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
            "audio_url": get_presigned_url(s.audio_file, "audio") if s.audio_file else None
        }
        for s in songs
    ])


# =========================================================
# CAPSULE (STATS)
# =========================================================

@app.route("/capsule/stats")
@jwt_required()
def capsule_stats():
    user_id = int(get_jwt_identity())
    
    # Optional: Filter by specific month/year (default to all-time or current month logic)
    # For now, let's do "All Time" to ensure data shows up, or "Last 30 Days"
    
    # 1. Total Minutes
    total_seconds = (
        db.session.query(func.sum(PlayLog.listen_duration))
        .filter(PlayLog.user_id == user_id)
        .scalar()
    ) or 0
    total_minutes = int(total_seconds / 60)
    
    # 2. Top Songs
    top_songs_res = (
        db.session.query(Song, func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .group_by(Song.id)
        .order_by(func.count(PlayLog.id).desc())
        .limit(5)
        .all()
    )
    
    top_songs = [
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": get_presigned_url(s.cover_file, "covers") if s.cover_file else None,
            "plays": plays
        }
        for s, plays in top_songs_res
    ]
    
    # 3. Top Artists
    top_artists_res = (
        db.session.query(Song.artist, func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .group_by(Song.artist)
        .order_by(func.count(PlayLog.id).desc())
        .limit(5)
        .all()
    )
    
    top_artists = [
        {"name": artist, "plays": plays}
        for artist, plays in top_artists_res
    ]
    
    # 4. Top Genres (Simple)
    top_genres_res = (
        db.session.query(Song.genre, func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .group_by(Song.genre)
        .order_by(func.count(PlayLog.id).desc())
        .limit(3)
        .all()
    )
    
    top_genres = [
        {"genre": genre, "plays": plays} 
        for genre, plays in top_genres_res if genre and genre != "Unknown"
    ]
    
    return jsonify({
        "total_minutes": total_minutes,
        "total_seconds": total_seconds,
        "top_songs": top_songs,
        "top_artists": top_artists,
        "top_genres": top_genres,
        "generated_at": datetime.utcnow().isoformat()
    })


# =========================================================
# INIT
# =========================================================

with app.app_context():
    if is_dev:
        db.create_all()
        auto_import_songs()

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        # Auto-migration for cover_file
        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE playlist ADD COLUMN cover_file VARCHAR(255)"))
            db.session.commit()
            print("Auto-migrated: Added cover_file to playlist")
        except Exception as e:
            pass

        # Auto-migration for PlayLog
        try:
            db.session.execute(text("ALTER TABLE play_logs ADD COLUMN completed BOOLEAN DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added completed to play_logs")
        except Exception:
            pass

        try:
            db.session.execute(text("ALTER TABLE play_logs ADD COLUMN listen_duration INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added listen_duration to play_logs")
        except Exception:
            pass

        # Auto-migration for Song upgrades
        try:
            db.session.execute(text("ALTER TABLE song ADD COLUMN duration INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added duration to song")
        except Exception:
            pass

        try:
            db.session.execute(text("ALTER TABLE song ADD COLUMN play_count INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added play_count to song")
        except Exception:
            pass

        try:
            db.session.execute(text("ALTER TABLE song ADD COLUMN audio_hash VARCHAR(64)"))
            db.session.commit()
            print("Auto-migrated: Added audio_hash to song")
        except Exception:
            pass

    socketio.run(app, debug=True, host="0.0.0.0", port=5000)

# =========================================================
# SPOTIFY IMPORT (via Scraping + yt-dlp)
# =========================================================
import subprocess
import requests
import re
import base64

def fetch_spotify_tracks(playlist_url):
    """
    Scrapes the Spotify playlist page for the 'initialState' script,
    decodes it (Base64 -> JSON), and extracts tracks.
    Returns a list of clean "Title - Artist" strings.
    """
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        r = requests.get(playlist_url, headers=headers)
        if r.status_code != 200:
            print(f"Failed to fetch Spotify page: {r.status_code}")
            return []
            
        html = r.text
        
        # Look for <script id="initialState" type="text/plain">BASE64...</script>
        match = re.search(r'<script id="initialState" type="text/plain">(.*?)</script>', html)
        if not match:
            print("Could not find initialState in Spotify page")
            return []

        b64_data = match.group(1)
        decoded = base64.b64decode(b64_data).decode('utf-8')
        data = json.loads(decoded)
        
        tracks = []
        
        # Traverse: entities -> items -> spotify:playlist:ID -> content -> items
        entities = data.get("entities", {}).get("items", {})
        
        # Find the playlist key (key containing "spotify:playlist")
        playlist_key = next((k for k in entities.keys() if "spotify:playlist" in k), None)
        
        if playlist_key:
            playlist_data = entities[playlist_key]
            items = playlist_data.get("content", {}).get("items", [])
            
            for item in items:
                track = item.get("itemV2", {}).get("data", {})
                title = track.get("name")
                
                # Extract first artist or all? All is better for search uniqueness
                artist_list = track.get("artists", {}).get("items", [])
                artists = [a.get("profile", {}).get("name") for a in artist_list if a.get("profile")]
                
                if title:
                    if artists:
                        # Join first 2 artists maybe?
                        artist_str = ", ".join(artists[:2]) 
                        tracks.append(f"{title} - {artist_str}")
                    else:
                        tracks.append(title)
                        
        return tracks

    except Exception as e:
        print(f"Failed to parse spotify playlist: {e}")
        return []

def find_and_download_song(query):
    """
    1. Search DB for existing song (simple fuzzy match not implemented yet, doing exact check).
    2. If not found, download via yt-dlp.
    Returns Song object or None.
    """
    try:
        # Construct specific filename to avoid duplicates/collisions
        temp_id = uuid.uuid4().hex
        
        # Search and download best audio
        # ytsearch1: "Title Artist"
        cmd = [
            "yt-dlp",
            f"ytsearch1:{query}",
            "-x", "--audio-format", "mp3",
            "--add-metadata",
            "--embed-thumbnail",
            "-o", f"{app.config['UPLOAD_AUDIO']}/{temp_id}.%(ext)s",
            "--print-json" # print metadata
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            print(f"Download failed for {query}: {result.stderr}")
            return None

        # Parse JSON metadata from stdout (it might be mixed with logs, so split lines)
        info = None
        for line in result.stdout.split('\n'):
            try:
                line_json = json.loads(line)
                if "title" in line_json:
                    info = line_json
                    break
            except:
                pass
                
        if not info:
            return None

        # Determine filename
        ext = "mp3" 
        filename = f"{temp_id}.{ext}"
        filepath = os.path.join(app.config['UPLOAD_AUDIO'], filename)
        
        if not os.path.exists(filepath):
            # fallback checks
            return None

        # Create Song Record
        # Extract metadata
        title = info.get("title", query)
        uploader = info.get("uploader", "Unknown")
        
        # Extract Cover
        cover_filename = f"{temp_id}.jpg"
        cover_path = os.path.join(app.config['UPLOAD_COVER'], cover_filename)
        
        thumbnail_url = info.get("thumbnail")
        if thumbnail_url:
             import requests
             try:
                 r = requests.get(thumbnail_url)
                 if r.status_code == 200:
                     with open(cover_path, 'wb') as f:
                         f.write(r.content)
             except:
                 cover_filename = None # failed

        song = Song(
            title=title,
            artist=uploader,
            album="Imported",
            audio_file=filename,
            cover_file=cover_filename,
            genre="Imported"
        )
        db.session.add(song)
        db.session.commit()
        return song

    except Exception as e:
        print(f"Download exception: {e}")
        return None


@app.route("/playlists/import/spotify", methods=["POST"])
@jwt_required()
def import_spotify_playlist():
    print(">>> INVOKED: import_spotify_playlist")
    user_id = int(get_jwt_identity())
    # user_id = 1 # Mock user ID for testing
    data = request.json
    url = data.get("url")
    print(f"Import URL: {url}")
    
    if not url:
        return jsonify(error="URL required"), 400

    # Clean URL (remove query params)
    url = url.split('?')[0]

    track_queries = fetch_spotify_tracks(url)
    
    if not track_queries:
        return jsonify(error="Could not find tracks or playlist is invalid"), 400

    playlist = Playlist(
        name=f"Imported Playlist {datetime.now().strftime('%H:%M')}",
        owner_id=user_id
    )
    db.session.add(playlist)
    db.session.commit()

    success_count = 0
    max_songs = 10
    
    imported_songs = []
    
    for q in track_queries[:max_songs]:
        song = find_and_download_song(q)
        if song:
            item = PlaylistSong(playlist_id=playlist.id, song_id=song.id)
            db.session.add(item)
            success_count += 1
            imported_songs.append(song.title)
    
    db.session.commit()
    
    return jsonify({
        "msg": f"Imported {success_count} songs",
        "playlist_id": playlist.id,
        "playlist_name": playlist.name,
        "tracks": imported_songs
    })
# =========================================================
# HISTORY & CAPSULE
# =========================================================

# Debug Ping
@app.route("/ping", methods=["GET"])
def ping():
    return jsonify(msg="pong")

# 1. Record Play
@app.route("/player/record-play", methods=["POST", "OPTIONS"])
def record_play():
    if request.method == "OPTIONS":
        return jsonify(msg="Preflight OK")

    verify_jwt_in_request()
    user_id = int(get_jwt_identity())
    data = request.json or {}
    song_id = data.get("song_id")
    duration = int(data.get("duration", 0))  # Accept duration from client

    if not song_id:
        return jsonify(error="song_id required"), 400
    
    # Verify song exists
    try:
        song_id = int(song_id) # Ensure int
        song = Song.query.get(song_id)
        if not song:
            print(f"⚠️ record_play: Song {song_id} not found (ignored)")
            return jsonify(msg="Song ignored"), 200

        # Log it with duration
        log = PlayLog(
            user_id=user_id,
            song_id=song_id,
            played_at=datetime.utcnow(),
            completed=True,
            listen_duration=duration  # Use actual duration from client
        )
        db.session.add(log)
        db.session.commit()
        print(f"✅ record_play: Logged song {song_id} for user {user_id} (duration: {duration}s)")

        return jsonify(msg="Recorded")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ record_play CRASH: {e}")
        return jsonify(error=str(e)), 500

# 1.5 Get User Profile
@app.route("/me", methods=["GET"])
@jwt_required()
def get_user_profile():
    user_id = int(get_jwt_identity())
    user = User.query.get(user_id)
    if not user:
        return jsonify(error="User not found"), 404
        
    return jsonify({
        "id": user.id,
        "username": user.username,
        "email": user.email
    })


@app.route("/me/recent")
@jwt_required()
def get_recent():
    user_id = int(get_jwt_identity())
    
    # Get last 50 plays
    logs = (
        db.session.query(PlayLog, Song)
        .join(Song, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .order_by(PlayLog.played_at.desc())
        .limit(50)
        .all()
    )

    # Dedup by song_id consecutive? Or just list them? 
    # Usually recents is a straight list. 
    # Let's map to song objects.
    
    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None,
            "played_at": log.played_at.isoformat()
        }
        for log, s in logs
    ])

# 2. Get User Streak & Stats
@app.route("/me/streak")
@jwt_required()
def get_streak_stats():
    user_id = int(get_jwt_identity())
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 1. Minutes Played Today
    # Sum listen_duration for plays today
    todays_play_time = (
        db.session.query(func.sum(PlayLog.listen_duration))
        .filter(PlayLog.user_id == user_id)
        .filter(PlayLog.played_at >= today_start)
        .scalar()
    ) or 0
    minutes_today = int(todays_play_time / 60)

    # 2. Top Genre (Last 7 Days)
    week_start = today_start - timedelta(days=7)
    top_genre_entry = (
        db.session.query(Song.genre, func.count(PlayLog.id).label("count"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .filter(PlayLog.played_at >= week_start)
        .filter(Song.genre != None)
        .filter(Song.genre != "Unknown")
        .group_by(Song.genre)
        .order_by(desc("count"))
        .first()
    )
    top_genre = top_genre_entry[0] if top_genre_entry else "Music"

    # 3. Calculate Streak (Consecutive Days Active)
    # Get all distinct dates user played music, ordered desc
    # SQLite 'date()' function might differ from Postgres. verify usage.
    # For compatibility, we fetch dates and process in python (safer for small-med scale)
    
    # Efficient enough: Fetch distinct dates from last 365 days
    year_start = today_start - timedelta(days=365)
    
    # SQLAlchemy logic for "date(played_at)"
    # SQL: SELECT DISTINCT date(played_at) FROM play_logs WHERE ...
    # This varies by DB. 
    # Let's just fetch all 'played_at' for the user in last month/year and compute set in python
    # To be safe against massive logs, just selecting dates is better but we might have many logs.
    # Let's try to group by date in SQL if possible, but fallback to python for safety across SQLite/PG.
    
    logs = (
        db.session.query(PlayLog.played_at)
        .filter(PlayLog.user_id == user_id)
        .filter(PlayLog.played_at >= year_start)
        .order_by(PlayLog.played_at.desc())
        .all()
    )
    
    active_dates = {log.played_at.date() for log in logs}
    
    streak = 0
    check_date = now.date()
    
    # If played today, streak starts today. If not, check yesterday.
    if check_date not in active_dates:
        check_date = check_date - timedelta(days=1)
        if check_date not in active_dates:
             # Streak broken or 0
             pass
        else:
             streak = 1
             check_date = check_date - timedelta(days=1)
    else:
        streak = 1
        check_date = check_date - timedelta(days=1)

    # Count backwards
    while check_date in active_dates:
        streak += 1
        check_date = check_date - timedelta(days=1)

    return jsonify({
        "streak_days": streak,
        "minutes_today": minutes_today,
        "top_genre": top_genre
    })

# 3. Capsule Stats
@app.route("/capsule/stats")
@jwt_required()
def get_capsule_stats():
    user_id = int(get_jwt_identity())
    

    total_plays = PlayLog.query.filter_by(user_id=user_id).count()
    total_minutes = total_plays * 3 # Rough estimate: 3 mins per song
    
    # Top Songs
    top_songs_raw = (
        db.session.query(Song, db.func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .group_by(Song.id)
        .order_by(desc("plays"))
        .limit(5)
        .all()
    )
    
    top_songs = [
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None,
            "plays": plays
        }
        for s, plays in top_songs_raw
    ]
    
    # Top Artists
    # Sqlite group by artist string
    top_artists_raw = (
        db.session.query(Song.artist, db.func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .group_by(Song.artist)
        .order_by(desc("plays"))
        .limit(5)
        .all()
    )
    
    top_artists = [{"name": a, "plays": p} for a, p in top_artists_raw]

    # Top Genres
    top_genres_raw = (
        db.session.query(Song.genre, db.func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .filter(PlayLog.user_id == user_id)
        .filter(Song.genre != None)
        .group_by(Song.genre)
        .order_by(desc("plays"))
        .limit(5)
        .all()
    )
    
    top_genres = [{"genre": g, "plays": p} for g, p in top_genres_raw]

    return jsonify({
        "total_minutes": total_minutes,
        "top_songs": top_songs,
        "top_artists": top_artists,
        "top_genres": top_genres
    })


# =========================================================
# R2 SYNC (For Render)
# =========================================================
def sync_r2_songs():
    """
    Syncs songs from Cloudflare R2 bucket to the database.
    Required Env Vars: R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME
    """
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        print("⚠️ boto3 not installed. Skipping R2 sync.")
        return

    r2_account_id = os.environ.get("R2_ACCOUNT_ID")
    r2_access_key = os.environ.get("R2_ACCESS_KEY_ID")
    r2_secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    r2_bucket_name = os.environ.get("R2_BUCKET_NAME")

    # If credentials are missing, we skip (it might be local dev)
    if not all([r2_account_id, r2_access_key, r2_secret_key, r2_bucket_name]):
        if os.environ.get("FLASK_ENV") == "production":
            print("⚠️ R2 credentials missing in production. Skipping R2 sync.")
        return

    print(f"🔄 Starting R2 Sync from bucket: {r2_bucket_name}")

    try:
        s3 = boto3.client('s3',
            endpoint_url=os.environ.get("R2_ENDPOINT_URL"),
            aws_access_key_id=os.environ.get("R2_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("R2_SECRET_ACCESS_KEY"),
            region_name="auto"
        )
        
        paginator = s3.get_paginator('list_objects_v2')
        
        # 1. Scan for Covers first (to match efficiently)
        r2_covers = set()
        print("🔄 Scanning R2 Covers...")
        for page in paginator.paginate(Bucket=r2_bucket_name, Prefix='covers/'):
            if 'Contents' in page:
                for obj in page['Contents']:
                    if obj['Key'].lower().endswith(('.jpg', '.jpeg', '.png')):
                        r2_covers.add(obj['Key'])
        print(f"   -> Found {len(r2_covers)} covers.")

        # 2. Scan for Audio
        print(f"🔄 Starting R2 Sync from bucket: {r2_bucket_name}")
        pages = paginator.paginate(Bucket=r2_bucket_name, Prefix='audio/')
        
        current_files = set()
        count = 0

        for page in pages:
            if 'Contents' not in page:
                continue
            
            for obj in page['Contents']:
                file_key = obj['Key']
                # file_key is "audio/filename.mp3"
                if not file_key.lower().endswith('.mp3'):
                    continue
                
                filename = os.path.basename(file_key)
                current_files.add(filename)
                
                # Check if exists in DB (Case-insensitive check is safer)
                exists = Song.query.filter(func.lower(Song.audio_file) == filename.lower()).first()
                if exists:
                    if not exists.cover_file:
                        basename_no_ext = os.path.splitext(filename)[0]
                        cover_key = None
                        search_bases = [
                            basename_no_ext,
                            basename_no_ext.replace(" ", "_"),
                            basename_no_ext.replace(" ", "-"),
                        ]
                        
                        for base in search_bases:
                            for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                                candidates = [
                                    f"covers/{base}{ext}",
                                    f"covers/{base}_cover{ext}",
                                ]
                                for cand in candidates:
                                    if cand in r2_covers:
                                        cover_key = os.path.basename(cand)
                                        break
                                if cover_key: break
                            if cover_key: break
                        
                        if cover_key:
                            print(f"   🩹 Healing missing cover for: {exists.title} -> Found {cover_key}")
                            exists.cover_file = cover_key
                            db.session.commit()
                    continue

                # Add to DB
                # Parse filename: "Artist - Title.mp3"
                basename_no_ext = os.path.splitext(filename)[0]
                
                # Robust parsing strategies
                if ' - ' in basename_no_ext:
                    parts = basename_no_ext.split(' - ', 1)
                    artist = parts[0].strip()
                    title = parts[1].strip()
                elif '_-_' in basename_no_ext:
                    parts = basename_no_ext.split('_-_', 1)
                    artist = parts[0].replace('_', ' ').strip()
                    title = parts[1].replace('_', ' ').strip()
                else:
                    artist = "Unknown" # Changed from (R2) to see if update applied
                    title = basename_no_ext.replace('_', ' ')

                # Clean title (remove [Official Video] etc if present)
                title = re.sub(r'\s*\[.*?\]', '', title).strip()

                # Check for cover match
                # e.g. "audio/Artist - Title.mp3" tries to find "covers/Artist - Title.jpg/png/jpeg"
                cover_key = None
                search_bases = [
                    basename_no_ext,
                    basename_no_ext.replace(" ", "_"),
                    basename_no_ext.replace(" ", "-"),
                ]
                
                for base in search_bases:
                    for ext in ['.jpg', '.jpeg', '.png', '.webp']:
                        candidates = [
                            f"covers/{base}{ext}",
                            f"covers/{base}_cover{ext}",
                        ]
                        for cand in candidates:
                            if cand in r2_covers:
                                cover_key = os.path.basename(cand)
                                break
                        if cover_key: break
                    if cover_key: break
                
                try:
                    song = Song(
                        title=title,
                        artist=artist,
                        album="R2 Import",
                        audio_file=filename,
                        cover_file=cover_key,
                        genre="Unknown",
                        uploaded_by=None
                    )
                    db.session.add(song)
                    db.session.commit() # Commit individually to isolate errors
                    count += 1
                    print(f"   -> Imported: {title} by {artist} (Cover: {'✅' if cover_key else '❌'})")
                except IntegrityError:
                    db.session.rollback()
                    print(f"   ⚠️ Skipping duplicate (Integrity Error): {filename}")
                except Exception as e:
                    db.session.rollback()
                    print(f"   ❌ Error importing {filename}: {e}")

        if count > 0:
            print(f"✅ R2 Sync complete. Imported {count} new songs.")
        else:
             print("✅ R2 Sync complete. No new songs found.")

    except Exception as e:
        print(f"❌ R2 Sync Failed: {e}")

# =========================================================
# KEEP-ALIVE (FOR RENDER FREE TIER)
# =========================================================

def keep_alive_ping():
    """Pings the backend health endpoint every 10 minutes to prevent sleeping."""
    # Wait for the server to start
    time.sleep(10)
    url = "https://api.kreewaux.xyz/health"
    print(f"🚀 Keep-alive thread started, targeting {url}")
    
    while True:
        try:
            # We don't care about the response, just that the request hit the server
            requests.get(url, timeout=10)
            print(f"📡 Keep-alive ping sent to {url}")
        except Exception as e:
            print(f"⚠️ Keep-alive ping failed: {e}")
        time.sleep(600)  # 10 minutes

# Start the keep-alive thread as a daemon
threading.Thread(target=keep_alive_ping, daemon=True).start()


# =========================================================
# STATS & ANALYTICS (NEW)
# =========================================================

@app.route("/stats/global", methods=["GET"])
def global_stats():
    """Get most played songs platform-wide"""
    limit = int(request.args.get("limit", 20))
    
    results = (
        db.session.query(Song, func.count(PlayLog.id).label("plays"))
        .join(PlayLog, PlayLog.song_id == Song.id)
        .group_by(Song.id)
        .order_by(desc("plays"))
        .limit(limit)
        .all()
    ) 
    
    return jsonify([
        {
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "cover": full_url(f"/covers/{s.cover_file}") if s.cover_file else None,
            "plays": plays
        }
        for s, plays in results
    ])

@app.route("/stats/song/<int:song_id>", methods=["GET"])
def song_stats(song_id):
    """Get specific stats for one song"""
    song = Song.query.get_or_404(song_id)
    
    total_plays = PlayLog.query.filter_by(song_id=song_id).count()
    unique_listeners = db.session.query(func.count(func.distinct(PlayLog.user_id))).filter_by(song_id=song_id).scalar()
    
    return jsonify({
        "id": song.id,
        "title": song.title,
        "plays": total_plays,
        "unique_listeners": unique_listeners
    })

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        # Auto-migration for cover_file
        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE playlist ADD COLUMN cover_file VARCHAR(255)"))
            db.session.commit()
            print("Auto-migrated: Added cover_file to playlist")
        except Exception as e:
            pass

        # Auto-migration for PlayLog
        try:
            db.session.execute(text("ALTER TABLE play_logs ADD COLUMN completed BOOLEAN DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added completed to play_logs")
        except Exception:
            pass

        try:
            db.session.execute(text("ALTER TABLE play_logs ADD COLUMN listen_duration INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added listen_duration to play_logs")
        except Exception:
            pass

        # Auto-migration for Song upgrades
        try:
            db.session.execute(text("ALTER TABLE song ADD COLUMN duration INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added duration to song")
        except Exception:
            pass

        try:
            db.session.execute(text("ALTER TABLE song ADD COLUMN play_count INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated: Added play_count to song")
        except Exception:
            pass

        try:
            db.session.execute(text("ALTER TABLE song ADD COLUMN audio_hash VARCHAR(64)"))
            db.session.commit()
            print("Auto-migrated: Added audio_hash to song")
        except Exception:
            pass
            
        # Auto-import songs on startup
        try:
            auto_import_songs()
        except Exception as e:
            print(f"Auto-import failed: {e}")
            
        # Sync with R2 (Production)
        try:
            sync_r2_songs()
        except Exception as e:
            print(f"R2 Sync failed: {e}")



    socketio.run(app, debug=True, host="0.0.0.0", port=5000)

# =========================================================
# PRODUCTION STARTUP (GUNICORN)
# =========================================================
else:
    # This block runs when imported (e.g. by gunicorn)
    with app.app_context():
        # Auto-migration for Song upgrades (Gunicorn/Render Production)
        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE song ADD COLUMN duration INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated (Prod): Added duration to song")
        except Exception:
            pass

        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE song ADD COLUMN play_count INTEGER DEFAULT 0"))
            db.session.commit()
            print("Auto-migrated (Prod): Added play_count to song")
        except Exception:
            pass

        try:
            from sqlalchemy import text
            db.session.execute(text("ALTER TABLE song ADD COLUMN audio_hash VARCHAR(64)"))
            db.session.commit()
            print("Auto-migrated (Prod): Added audio_hash to song")
        except Exception:
            pass
            
        try:
            print("🚀 Gunicorn startup: Syncing R2...")
            sync_r2_songs()
        except Exception as e:
            print(f"Startup Sync Error: {e}")