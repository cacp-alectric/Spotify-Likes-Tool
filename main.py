import os
import dotenv
import mutagen.mp3
import mutagen.flac
import spotipy
from spotipy.oauth2 import SpotifyOAuth

# Load your credentials from the .env file
dotenv.load_dotenv(dotenv_path="Credentials/credentials.env")

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=os.getenv("CLIENT_ID"),
    client_secret=os.getenv("CLIENT_SECRET"),
    redirect_uri="http://127.0.0.1:8000/callback",
    scope="user-library-read"
))

results = sp.current_user_saved_tracks(limit=20, offset=0)
for item in results['items']:
    track = item['track']
    print(track['artists'][0]['name'], "-", track['name'])

