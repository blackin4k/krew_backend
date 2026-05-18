import requests


def main():
    base = "http://127.0.0.1:5000"

    login_response = requests.post(
        f"{base}/auth/login",
        json={
            "username": "testuser",
            "password": "123456",
        },
    )
    print("login:", login_response.text)

    token = login_response.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    songs = requests.get(f"{base}/songs").json()
    sid = songs[0]["id"]

    requests.post(f"{base}/player/play", json={"song_id": sid}, headers=headers)
    requests.post(f"{base}/player/next", headers=headers)
    requests.get(f"{base}/songs/{sid}/stream")

    print("✅ backend is alive")


if __name__ == "__main__":
    main()
