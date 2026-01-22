
import json
import os
from app import app, db, User, Song, create_access_token

def test_record_play():
    # Setup context
    with app.app_context():
        # 1. Get a user
        user = User.query.first()
        if not user:
            print("❌ No users found in DB. Cannot test.")
            return

        # 2. Get a song
        song = Song.query.first()
        if not song:
            print("❌ No songs found in DB. Cannot test.")
            return

        print(f"ℹ️ Testing with User: {user.username} (ID: {user.id})")
        print(f"ℹ️ Testing with Song: {song.title} (ID: {song.id})")

        # 3. Generate Token
        token = create_access_token(identity=str(user.id))
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # 4. Create Test Client
        client = app.test_client()

        # 5. Make Request
        print("🚀 Sending POST /player/record-play...")
        resp = client.post(
            "/player/record-play",
            headers=headers,
            json={"song_id": song.id}
        )

        print(f"📡 Status Code: {resp.status_code}")
        try:
            print(f"📄 Response Body: {json.dumps(resp.json, indent=2)}")
        except:
            print(f"📄 Raw Response: {resp.data}")

if __name__ == "__main__":
    test_record_play()
