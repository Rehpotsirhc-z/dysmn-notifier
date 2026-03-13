#!/usr/bin/env python3
#!/usr/bin/env python3

import os
import requests
from datetime import datetime, timezone

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
ARTIST_ID = os.getenv("SPOTIFY_ARTIST_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
KNOWN_IDS_FILE = "known_album_ids.txt"


def get_access_token(client_id, client_secret):
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_all_artist_albums(artist_id, token):
    """Fetch ALL albums (singles, albums, compilations, appears_on)."""
    url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"
    params = {
        "include_groups": "single,album,appears_on,compilation",
        "limit": 50,
    }
    headers = {"Authorization": f"Bearer {token}"}
    albums = []
    while url:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        albums.extend(data["items"])
        url = data.get("next")
        params = None
    return albums


def load_known_ids():
    """Return a set of album IDs that have already been seen.
    Returns None if the file does not exist (first run)."""
    if not os.path.exists(KNOWN_IDS_FILE):
        return None
    with open(KNOWN_IDS_FILE, "r") as f:
        return {line.strip() for line in f if line.strip()}


def save_known_ids(albums):
    """Overwrite known IDs file with the IDs of all given albums."""
    with open(KNOWN_IDS_FILE, "w") as f:
        for album in albums:
            f.write(album["id"] + "\n")


def send_discord_notification(webhook_url, new_releases):
    message = "**New releases found!**\n"
    for a in new_releases:
        message += f"- [{a['name']}]({a['external_urls']['spotify']}) ({a['album_type']}) – {a['release_date']}\n"
    requests.post(webhook_url, json={"content": message})


def main():
    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    albums = get_all_artist_albums(ARTIST_ID, token)
    print(f"Total releases fetched: {len(albums)}")

    albums_sorted = sorted(albums, key=lambda a: a["release_date"], reverse=True)
    print("\nLatest 10 releases (any type):")
    for a in albums_sorted[:10]:
        print(f"- {a['name']} ({a['album_type']}) – {a['release_date']} {a['external_urls']['spotify']}")

    known_ids = load_known_ids()

    if known_ids is None:
        save_known_ids(albums)
        print("\nNo previous known IDs found. Initialised known_album_ids.txt with current releases.")
        print("No notifications sent this time – future runs will detect new releases.")
        return

    new_releases = [a for a in albums if a["id"] not in known_ids]

    if new_releases:
        print(f"\n✅ {len(new_releases)} new release(s) detected!")
        if DISCORD_WEBHOOK_URL:
            send_discord_notification(DISCORD_WEBHOOK_URL, new_releases)
            print("Discord notification sent.")
        else:
            print("Discord webhook not configured – skipping notification.")
    else:
        print(f"\nNo new releases – total known IDs: {len(known_ids)}.")

    save_known_ids(albums)


if __name__ == "__main__":
    main()
