
import requests

url = "http://localhost:5000/player/record-play"
print(f"📡 Sending OPTIONS to {url}")

try:
    r = requests.options(url, headers={"Origin": "http://test.com"})
    print(f"Status: {r.status_code}")
    print("Headers:")
    for k, v in r.headers.items():
        print(f"  {k}: {v}")
    
    if "Access-Control-Allow-Origin" in r.headers:
        print("✅ CORS Header Present")
    else:
        print("❌ CORS Header MISSING")
except Exception as e:
    print(f"❌ Failed: {e}")
