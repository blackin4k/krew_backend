import socketio
import time
import sys

# Configuration
BASE_URL = "http://localhost:5000"

# Colors for output
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

def test_jam_sync():
    print("Starting Jam Synchronization Test...")

    # Create two clients
    host_client = socketio.Client(logger=False, engineio_logger=False)
    listener_client = socketio.Client(logger=False, engineio_logger=False)

    # State tracking
    jam_id = "test_jam_123"
    listener_msgs = []
    
    # Mock tokens (backend decodes token to get user_id)
    # We need valid tokens or mock the backend verification.
    # Looking at app.py: socket_user_id uses decode_token(token). 
    # Ideally we should register/login to get real tokens, but for simplicity let's assume we can get them or the backend is in dev mode ?
    # Wait, app.py uses flask_jwt_extended. We need real tokens.
    
    # Let's write a helper to get tokens first
    import requests
    
    def get_token(username):
        # Register if needed
        requests.post(f"{BASE_URL}/auth/register", json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "password123"
        })
        # Login
        res = requests.post(f"{BASE_URL}/auth/login", json={
            "username": username,
            "password": "password123"
        })
        if res.status_code != 200:
            print(f"{RED}Failed to login {username}: {res.text}{RESET}")
            sys.exit(1)
        return res.json()["token"]

    print("🔑 Authenticating users...")
    host_token = get_token("host_user")
    listener_token = get_token("listener_user")
    
    # Listener Handlers
    @listener_client.on("jam:play")
    def on_play(data):
        print(f"Listener received PLAY: {data}")
        listener_msgs.append(("play", data))

    @listener_client.on("jam:pause")
    def on_pause(data):
        print(f"Listener received PAUSE: {data}")
        listener_msgs.append(("pause", data))

    try:
        # Connect
        print("🔌 Connecting sockets...")
        host_client.connect(BASE_URL, transports=['websocket', 'polling'])
        listener_client.connect(BASE_URL, transports=['websocket', 'polling'])

        # Host creates/joins jam
        print("🎤 Host joining jam...")
        host_client.emit("jam:join", {"jam_id": jam_id, "token": host_token})
        time.sleep(1)

        # Listener joins jam
        print("🎧 Listener joining jam...")
        listener_client.emit("jam:join", {"jam_id": jam_id, "token": listener_token})
        time.sleep(1)

        # 1. Host plays song at 0.0
        print("▶ Host playing song at 0.0...")
        host_client.emit("jam:play", {
            "jam_id": jam_id,
            "token": host_token,
            "song_id": 1,
            "position": 0.0
        })
        time.sleep(1)
        
        # Verify
        if not listener_msgs or listener_msgs[-1][0] != "play" or listener_msgs[-1][1]["position"] != 0.0:
            print(f"{RED}FAIL: Listener did not receive play at 0.0{RESET}")
            return
        
        # 2. Simulate time passing (2s)
        time.sleep(2)
        
        # 3. Host pauses at 2.0
        print("⏸ Host pausing at 2.0...")
        host_client.emit("jam:pause", {
            "jam_id": jam_id,
            "token": host_token,
            "song_id": 1, 
            "position": 2.0
        })
        time.sleep(1)
        
        if listener_msgs[-1][0] != "pause" or listener_msgs[-1][1]["position"] != 2.0:
             print(f"{RED}FAIL: Listener did not receive pause at 2.0{RESET}")
             return

        # 4. Host resumes at 2.0
        print("▶ Host resuming at 2.0...")
        host_client.emit("jam:play", {
            "jam_id": jam_id,
            "token": host_token,
            "song_id": 1,
            "position": 2.0
        })
        time.sleep(1)

        # Verify final state
        last_msg = listener_msgs[-1]
        if last_msg[0] == "play" and last_msg[1]["position"] == 2.0:
            print(f"{GREEN}SUCCESS: Listener received resume at 2.0{RESET}")
        else:
            print(f"{RED}FAIL: Listener received {last_msg}, expected play at 2.0{RESET}")

    except Exception as e:
        print(f"{RED}Error: {e}{RESET}")
    finally:
        host_client.disconnect()
        listener_client.disconnect()

if __name__ == "__main__":
    test_jam_sync()
