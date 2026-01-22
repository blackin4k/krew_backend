
import requests
import json

BASE_URL = "http://localhost:5000"

def check_backend():
    print(f"📡 Pinging {BASE_URL}...")
    try:
        # 1. Check Root (Health Check roughly)
        r = requests.get(BASE_URL)
        print(f"✅ Root: Status {r.status_code}")
    except Exception as e:
        print(f"❌ Root Check Failed: {e}")
        return

    # 2. Check Auth (to get token)
    # We need a token to hit record-play
    print("🔑 Attempting Login...")
    try:
        r = requests.post(f"{BASE_URL}/auth/login", json={"username": "test", "password": "password"})
        # Might fail if user doesn't exist, but let's see if we get a 401 or 404 or Connection Error
        print(f"ℹ️ Login Response: {r.status_code}")
        
        # We can't easily record-play without a real valid token which requires a real user.
        # But if we got a 401, the server IS running.
        if r.status_code in [200, 401, 400]:
             print("✅ Server is RESPONDING to API requests.")
        else:
             print(f"⚠️ Unexpected Login Status: {r.status_code}")

    except Exception as e:
        print(f"❌ API Check Failed: {e}")

if __name__ == "__main__":
    check_backend()
