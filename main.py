import os
import sqlite3
import dotenv
from mutagen import File
from mutagen.easyid3 import EasyID3
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Load your credentials from the .env file
dotenv.load_dotenv(dotenv_path="Credentials/credentials.env")

def get_tags(filepath):
    if filepath.endswith(".mp3"):
        audio = EasyID3(filepath)
    else:
        audio = File(filepath)
    
    title = audio["title"][0] if "title" in audio else "Unknown"
    artist = audio["artist"][0] if "artist" in audio else "Unknown"
    return title, artist

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
    redirect_uri="http://127.0.0.1:8000/callback",
    scope="user-library-read"
))

MUSIC_DIR = "/home/cacp/Music" # Set this here to your music directory
EXTENSIONS = ('.mp3', '.flac') # You can add more extensions if you want

tracks = []
for root, dirs, files in os.walk(MUSIC_DIR):
    for filename in files:
        if filename.endswith(EXTENSIONS):
            filepath = os.path.join(root, filename)
            title, artist = get_tags(filepath)
            tracks.append({"title": title, "artist": artist})

print(f"Found {len(tracks)} tracks")

# Connect to SQLite database (or create it if it doesn't exist)
os.makedirs('Database', exist_ok=True)
conn = sqlite3.connect('Database/library.db')
c = conn.cursor()

c.execute("""
    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        artist TEXT
    )
""")

conn.commit()

c.executemany("INSERT INTO tracks (title, artist) VALUES (?, ?)", 
    [(t["title"], t["artist"]) for t in tracks])

conn.commit()

c.execute("""
    CREATE TABLE IF NOT EXISTS liked_tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        artist TEXT
    )
""")
conn.commit()

liked = []
offset = 0

while True:
    results = sp.current_user_saved_tracks(limit=50, offset=offset)
    if not results['items']:
        break
    for item in results['items']:
        track = item['track']
        liked.append({
            "title": track['name'],
            "artist": track['artists'][0]['name']
        })
    offset += 50

print(f"Found {len(liked)} liked songs")

c.executemany("INSERT INTO liked_tracks (title, artist) VALUES (?, ?)",
    [(t["title"], t["artist"]) for t in liked])
conn.commit()

c.execute("""
    SELECT liked_tracks.artist, liked_tracks.title
    FROM liked_tracks
    LEFT JOIN tracks
        ON LOWER(liked_tracks.title) = LOWER(tracks.title)
        AND LOWER(liked_tracks.artist) = LOWER(tracks.artist)
    WHERE tracks.id IS NULL
    ORDER BY liked_tracks.artist
""")

missing = c.fetchall()
print(f"\n{len(missing)} songs in Spotify likes not in local library:\n")
for artist, title in missing:
    print(f"{artist} - {title}")

conn.close()