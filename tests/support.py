import json
import os
import shutil
import tempfile
import unittest

os.environ["FLASK_ENV"] = "development"
os.environ["DATABASE_URL"] = f"sqlite:////tmp/krew_backend_unittest.sqlite3"
os.environ["JWT_SECRET_KEY"] = "unit-test-secret-key-with-32-bytes"
os.environ["ADMIN_SECRET"] = "unit-test-admin-secret"
os.environ["AUTO_IMPORT_LOCAL_SONGS"] = "0"
os.environ["AWS_EC2_METADATA_DISABLED"] = "true"
os.environ["R2_ENDPOINT_URL"] = "http://127.0.0.1:1"
os.environ["R2_ACCESS_KEY_ID"] = "test"
os.environ["R2_SECRET_ACCESS_KEY"] = "test"

import app as app_module


TEST_DB_PATH = "/tmp/krew_backend_unittest.sqlite3"
TEST_UPLOAD_ROOT = tempfile.mkdtemp(prefix="krew_backend_uploads_")
TEST_AUDIO_DIR = os.path.join(TEST_UPLOAD_ROOT, "audio")
TEST_COVER_DIR = os.path.join(TEST_UPLOAD_ROOT, "covers")
os.makedirs(TEST_AUDIO_DIR, exist_ok=True)
os.makedirs(TEST_COVER_DIR, exist_ok=True)

app = app_module.app
db = app_module.db
User = app_module.User
Song = app_module.Song
Playlist = app_module.Playlist
PlaylistSong = app_module.PlaylistSong
PlaybackState = app_module.PlaybackState
PlayLog = app_module.PlayLog
ArtistApplication = app_module.ArtistApplication

app.config.update(
    TESTING=True,
    RATELIMIT_ENABLED=False,
    UPLOAD_AUDIO=TEST_AUDIO_DIR,
    UPLOAD_COVER=TEST_COVER_DIR,
)

app_module.limiter.enabled = False
app_module.get_presigned_url = (
    lambda filename, folder: f"https://test.local/{folder}/{filename}" if filename else None
)


class DummyThread:
    def __init__(self, target=None, args=None, kwargs=None, daemon=None):
        self.target = target
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = daemon

    def start(self):
        return None


app_module.threading.Thread = DummyThread


def _clean_directory(path):
    for entry in os.listdir(path):
        entry_path = os.path.join(path, entry)
        if os.path.isdir(entry_path):
            shutil.rmtree(entry_path)
        else:
            os.remove(entry_path)


class FlaskBackendTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.session.remove()
        db.drop_all()
        db.create_all()
        _clean_directory(TEST_AUDIO_DIR)
        _clean_directory(TEST_COVER_DIR)

    def tearDown(self):
        db.session.remove()
        self.app_context.pop()

    def create_user(
        self,
        username,
        email=None,
        password="password123",
        is_admin=False,
        is_artist=False,
    ):
        user = User(
            username=username,
            email=email or f"{username}@example.com",
            password_hash=app_module.bcrypt.generate_password_hash(password).decode(),
            is_admin=is_admin,
            is_artist=is_artist,
        )
        db.session.add(user)
        db.session.commit()
        return user

    def login(self, username, password="password123"):
        response = self.client.post(
            "/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        return response.get_json()["token"]

    def auth_headers(self, user, password="password123"):
        token = self.login(user.username, password=password)
        return {"Authorization": f"Bearer {token}"}

    def create_song(
        self,
        title,
        artist="Artist",
        album="Album",
        genre="Genre",
        audio_file=None,
        cover_file=None,
        uploaded_by=None,
        audio_hash=None,
    ):
        song = Song(
            title=title,
            artist=artist,
            album=album,
            genre=genre,
            audio_file=audio_file or f"{title.lower().replace(' ', '_')}.mp3",
            cover_file=cover_file,
            uploaded_by=uploaded_by,
            audio_hash=audio_hash or f"hash-{title.lower().replace(' ', '-')}",
        )
        db.session.add(song)
        db.session.commit()
        return song

    def create_playlist(self, owner_id, name="Playlist"):
        playlist = Playlist(name=name, owner_id=owner_id)
        db.session.add(playlist)
        db.session.commit()
        return playlist

    def add_song_to_playlist(self, playlist_id, song_id):
        db.session.add(PlaylistSong(playlist_id=playlist_id, song_id=song_id))
        db.session.commit()

    def create_playback_state(
        self,
        user_id,
        current_song_id=None,
        original_queue=None,
        shuffled_queue=None,
        history=None,
        shuffle=False,
    ):
        state = PlaybackState(
            user_id=user_id,
            current_song_id=current_song_id,
            original_queue=json.dumps(original_queue or []),
            shuffled_queue=json.dumps(shuffled_queue or []),
            history=json.dumps(history or []),
            shuffle=shuffle,
        )
        db.session.add(state)
        db.session.commit()
        return state
