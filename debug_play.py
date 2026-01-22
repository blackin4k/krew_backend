import requests
import sys
import time
import json

BASE_URL = "http://127.0.0.1:5000"

def debug():
    try:
        # 1. Login
        print("Logging in...")
        # Try Register First
        try:
            requests.post(f"{BASE_URL}/auth/register", json={"email": "test@test.com", "username": "test", "password": "password"})
        except:
            pass
        
        # Then Login
        auth = requests.post(f"{BASE_URL}/auth/login", json={"email": "test@test.com", "username": "test", "password": "password"})
        
        if auth.status_code != 200:
            print(f"Login failed: {auth.text}")
            return
        
        token = auth.json().get("token")
        if not token:
            print(f"No token: {auth.text}")
            return

        headers = {"Authorization": f"Bearer {token}"}
        
        # 2. Get a Song to play
        print("Fetching songs...")
        songs_res = requests.get(f"{BASE_URL}/songs?page=1&limit=5", headers=headers)
        songs = songs_res.json().get("items", [])
        if not songs:
            print("No songs found to play.")
            return
            
        song1 = songs[0]
        print(f"Attempting to verify Play logic with Song ID: {song1['id']} ({song1['title']})")

        # 3. Call /player/play
        print(f"\n--- TEST 1: Play Song {song1['id']} ---")
        play_res = requests.post(f"{BASE_URL}/player/play", json={"song_id": song1['id']}, headers=headers)
        if play_res.status_code != 200:
            print(f"Play failed: {play_res.text}")
            return
        play_data = play_res.json()
        print(f"Playing: {play_data.get('title')} (ID: {play_data.get('id')})")

        # 4. Call /player/next
        print("\n--- TEST 2: Next Song ---")
        next_res = requests.post(f"{BASE_URL}/player/next", headers=headers)
        if next_res.status_code != 200:
            print(f"Next failed: {next_res.text}")
        else:
            next_data = next_res.json()
            print(f"Next Song: {next_data.get('title')} (ID: {next_data.get('id')})")
            if next_data.get('id') == song1['id']:
                print("FAIL: Next button played the SAME song!")
            else:
                print("PASS: Next button played a different song.")
                
        # 5. Call /player/prev (Should go back to song 1)
        print("\n--- TEST 3: Previous Song ---")
        # Go to next again to have some history properly? No, Play -> Next. History should have Song 1.
        # Current is Song 2. Prev should be Song 1.
        prev_res = requests.post(f"{BASE_URL}/player/prev", headers=headers)
        if prev_res.status_code != 200:
            print(f"Prev failed: {prev_res.text}")
        else:
            prev_data = prev_res.json()
            print(f"Prev Song: {prev_data.get('title')} (ID: {prev_data.get('id')})")
            if prev_data.get('id') == song1['id']:
                 print("PASS: Prev button returned to Song 1.")
            else:
                 print(f"FAIL: Prev button did NOT return to Song 1. Got {prev_data.get('id')}")

    except Exception as e:
        print(f"Crash: {e}")

if __name__ == "__main__":
    debug()
