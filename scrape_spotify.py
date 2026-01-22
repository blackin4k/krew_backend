import requests
import re
import json
import base64

# Use local file if available, else fetch
try:
    with open("spotify_dump.html", "r", encoding="utf-8") as f:
        html = f.read()
except:
    url = "https://open.spotify.com/playlist/4iWFFDakM87sokdYBc6MxT"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    r = requests.get(url, headers=headers)
    html = r.text

try:
    # Look for <script id="initialState" type="text/plain">BASE64...</script>
    match = re.search(r'<script id="initialState" type="text/plain">(.*?)</script>', html)
    if match:
        b64_data = match.group(1)
        decoded = base64.b64decode(b64_data).decode('utf-8')
        data = json.loads(decoded)
        
        print("Successfully decoded JSON!")
        
        # Traverse to find tracks
        # Structure often: entities -> items -> spotify:playlist:ID -> content -> items
        
        entities = data.get("entities", {}).get("items", {})
        # Find the playlist key
        playlist_key = next((k for k in entities.keys() if "spotify:playlist" in k), None)
        
        if playlist_key:
            print(f"Found playlist: {playlist_key}")
            playlist_data = entities[playlist_key]
            
            # content -> items
            items = playlist_data.get("content", {}).get("items", [])
            print(f"Found {len(items)} items")
            
            for item in items:
                track = item.get("itemV2", {}).get("data", {})
                name = track.get("name")
                artists = [a.get("profile", {}).get("name") for a in track.get("artists", {}).get("items", [])]
                
                print(f"{name} - {', '.join(artists)}")
        else:
            print("No playlist entity found")
            print(entities.keys())

    else:
        print("No initialState script found")
        print(html[:500])

except Exception as e:
    print(f"Error: {e}")

