# Krew Backend ⚙️

The Krew Backend is a Flask-based REST API that serves as the core engine for the Krew music streaming platform. It handles audio processing, user management, real-time synchronization, and data persistence.

## 🛠 Tech Stack

- **Framework**: Flask (Python)
- **Database**: PostgreSQL (via SQLAlchemy)
- **Real-time**: Flask-SocketIO
- **Security**: Flask-JWT-Extended, Flask-Bcrypt
- **Storage**: Cloudflare R2 (S3-compatible) via Boto3
- **Media**: Mutagen (Metadata extraction)
- **Concurrency**: Gevent
- **Rate Limiting**: Flask-Limiter

## 🚀 Core Features

- **Audio Ingestion**: Supports MP3, WAV, FLAC, M4A, and OGG uploads with automatic metadata extraction.
- **Hybrid Storage Engine**: Manages local audio/cover files and synchronizes them to Cloudflare R2 in the background.
- **Smart Queue Logic**: Implements "vibe-based" autoplay that fills user queues based on song characteristics.
- **User Analytics**: Tracks listening duration, top genres, and most-played artists.
- **Artist Management**: Dedicated routes for verified artists to upload and manage their discography.
- **Admin Tools**: Secret-protected routes for system-wide analytics and management.

## 🚦 Getting Started

### Prerequisites
- Python 3.10+
- PostgreSQL (for production)

### Installation
1. `python -m venv venv`
2. `source venv/bin/activate` (or `venv\Scripts\activate` on Windows)
3. `pip install -r requirements.txt`

### Configuration
Create a `.env` file based on `.env.example`:
```env
DATABASE_URL=postgresql://user:pass@localhost/krew
JWT_SECRET_KEY=your_secret_key
R2_ENDPOINT_URL=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
```

### Running the Server
```bash
python app.py
```

## 📄 API Documentation
The API follows standard REST patterns. Key endpoints include:
- `/auth`: Login/Register
- `/songs`: Upload and search
- `/player`: Playback state and queue management
- `/user-stats`: Personal listening analytics

## 📄 License
Internal project for Krew Music.
