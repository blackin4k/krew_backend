import requests

BASE = "http://127.0.0.1:5000"

# login
r = requests.post(f"{BASE}/auth/login", json={
    "username": "testuser",
    "password": "123456"
})

print("login:", r.text)

token = r.json()["token"]
headers = {"Authorization": f"Bearer {token}"}

# get songs
songs = requests.get(f"{BASE}/songs").json()
sid = songs[0]["id"]

# play
requests.post(f"{BASE}/player/play", json={"song_id": sid}, headers=headers)

# next
requests.post(f"{BASE}/player/next", headers=headers)

# stream
requests.get(f"{BASE}/songs/{sid}/stream")

print("✅ backend is alive")
