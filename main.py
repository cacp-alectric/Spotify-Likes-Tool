import os
import re
import csv
import sqlite3
import dotenv
from collections import defaultdict
from mutagen import File
from mutagen.easyid3 import EasyID3
import spotipy
from spotipy.oauth2 import SpotifyOAuth

dotenv.load_dotenv(dotenv_path="Credentials/credentials.env")

def get_tags(filepath):
    if filepath.endswith(".mp3"):
        audio = EasyID3(filepath)
    else:
        audio = File(filepath)
    title = audio["title"][0] if "title" in audio else "Unknown"
    artist = audio["artist"][0] if "artist" in audio else "Unknown"
    album = audio["album"][0] if "album" in audio else "Unknown"
    return title, artist, album

def normalize_title(name):
    if not name:
        return ""
    name = re.sub(r'\s*\(.*?(version|edit|mix|live|remaster|remastered|album|single|radio|mono|stereo|bonus|feat\.?.*).*?\)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\[.*?(version|edit|mix|live|remaster|remastered|album|single|radio|mono|stereo|bonus|feat\.?.*).*?\]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*-\s*.*?(remaster|remastered|version|edit|mix|live|mono|stereo).*$', '', name, flags=re.IGNORECASE)
    return name.strip()

def normalize_album(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'\s*\(.*?(deluxe|remaster|remastered|anniversary|expanded|edition|version|bonus).*?\)', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\[.*?(deluxe|remaster|remastered|anniversary|expanded|edition|version|bonus).*?\]', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*-\s*.*?(deluxe|remaster|remastered|anniversary|expanded|edition|version|bonus).*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\s*\(\d{4}\)', '', name)
    name = name.strip(" -").strip()
    return name

def normalize_artist(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(r'^the\s+', '', name)
    name = re.sub(r'^a\s+', '', name)
    name = re.sub(r'\s*&\s*', ' and ', name)
    name = re.sub(r'\s*feat\.?.*$', '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^\w\s]', '', name)
    return name.strip()

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
    redirect_uri="http://127.0.0.1:8000/callback",
    scope="user-library-read"
))

MUSIC_DIR = "/home/cacp/Music"
EXTENSIONS = ('.mp3', '.flac')

tracks = []
for root, dirs, files in os.walk(MUSIC_DIR):
    for filename in files:
        if filename.endswith(EXTENSIONS):
            filepath = os.path.join(root, filename)
            title, artist, album = get_tags(filepath)
            tracks.append({
                "title": title,
                "normalized_title": normalize_title(title),
                "artist": artist,
                "normalized_artist": normalize_artist(artist),
                "album": album,
                "normalized_album": normalize_album(album)
            })

print(f"Found {len(tracks)} local tracks")

os.makedirs('Database', exist_ok=True)
conn = sqlite3.connect('Database/library.db')
c = conn.cursor()

c.execute("""
    CREATE TABLE IF NOT EXISTS tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        normalized_title TEXT,
        artist TEXT,
        normalized_artist TEXT,
        album TEXT,
        normalized_album TEXT
    )
""")
conn.commit()

c.executemany("""
    INSERT INTO tracks (title, normalized_title, artist, normalized_artist, album, normalized_album)
    VALUES (?, ?, ?, ?, ?, ?)
""", [(t["title"], t["normalized_title"], t["artist"], t["normalized_artist"], t["album"], t["normalized_album"]) for t in tracks])
conn.commit()

c.execute("""
    CREATE TABLE IF NOT EXISTS liked_tracks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        normalized_title TEXT,
        artist TEXT,
        normalized_artist TEXT,
        album TEXT,
        normalized_album TEXT
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
        title = track['name']
        artist = track['artists'][0]['name']
        album = track['album']['name']
        liked.append({
            "title": title,
            "normalized_title": normalize_title(title),
            "artist": artist,
            "normalized_artist": normalize_artist(artist),
            "album": album,
            "normalized_album": normalize_album(album)
        })
    offset += 50

print(f"Found {len(liked)} liked songs")

c.executemany("""
    INSERT INTO liked_tracks (title, normalized_title, artist, normalized_artist, album, normalized_album)
    VALUES (?, ?, ?, ?, ?, ?)
""", [(t["title"], t["normalized_title"], t["artist"], t["normalized_artist"], t["album"], t["normalized_album"]) for t in liked])
conn.commit()

c.execute("""
    SELECT l.artist, l.title, l.album, l.normalized_artist, l.normalized_album
    FROM liked_tracks l
    LEFT JOIN tracks t
        ON l.normalized_title = t.normalized_title
        AND l.normalized_artist = t.normalized_artist
    WHERE t.id IS NULL
    ORDER BY l.artist
""")
missing = c.fetchall()

local_albums = set()
c.execute("SELECT DISTINCT normalized_artist, normalized_album FROM tracks")
for row in c.fetchall():
    local_albums.add((row[0], row[1]))

# Group by normalized keys only — fixes duplicate album/single entries
grouped = defaultdict(lambda: {"titles": [], "album_display": ""})
for artist, title, album, norm_artist, norm_album in missing:
    key = (artist, norm_artist, norm_album)
    grouped[key]["titles"].append(title)
    if not grouped[key]["album_display"]:
        grouped[key]["album_display"] = album

albums_missing = {}
singles_missing_raw = []

for (artist, norm_artist, norm_album), data in grouped.items():
    titles = data["titles"]
    album_display = data["album_display"]
    if (norm_artist, norm_album) in local_albums:
        for title in titles:
            singles_missing_raw.append((artist, title, album_display, norm_artist, norm_album))
    else:
        if len(titles) > 1:
            albums_missing[(artist, norm_artist, norm_album)] = {"titles": titles, "album_display": album_display}
        else:
            singles_missing_raw.append((artist, titles[0], album_display, norm_artist, norm_album))

# Exclude singles that belong to an album already in albums_missing
missing_album_keys = {(norm_artist, norm_album) for (artist, norm_artist, norm_album) in albums_missing.keys()}
singles_missing = [
    (artist, title, album)
    for artist, title, album, norm_artist, norm_album in singles_missing_raw
    if (norm_artist, norm_album) not in missing_album_keys
]

col1, col2, col3 = 30, 45, 5

print("\n" + "=" * 85)
print("ALBUMS MISSING")
print("=" * 85)
print(f"{'Artist':<{col1}} {'Album':<{col2}} {'Tracks':>{col3}}")
print("-" * 85)
for (artist, norm_artist, norm_album), data in sorted(albums_missing.items()):
    print(f"{artist:<{col1}} {data['album_display']:<{col2}} {len(data['titles']):>{col3}}")

print("\n" + "=" * 85)
print("SINGLES / PARTIAL")
print("=" * 85)
print(f"{'Artist':<{col1}} {'Title':<{col2}} {'Album'}")
print("-" * 85)
for artist, title, album in sorted(singles_missing):
    print(f"{artist:<{col1}} {title:<{col2}} {album}")

os.makedirs('Output', exist_ok=True)

with open('Output/missing_albums.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(["Artist", "Album", "Tracks Missing"])
    for (artist, norm_artist, norm_album), data in sorted(albums_missing.items()):
        writer.writerow([artist, data['album_display'], len(data['titles'])])

with open('Output/missing_singles.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(["Artist", "Title", "Album"])
    for artist, title, album in sorted(singles_missing):
        writer.writerow([artist, title, album])

print(f"\nSaved to Output/missing_albums.csv and Output/missing_singles.csv")

conn.close()