#!/usr/bin/env python3

import os
import requests
from datetime import datetime, timezone

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
ARTIST_ID = os.getenv("SPOTIFY_ARTIST_ID", "")
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
LAST_CHECK_FILE = "last_check.txt"


def get_access_token(client_id, client_secret):
    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={"grant_type": "client_credentials"},
        auth=(client_id, client_secret),
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def get_all_artist_albums(artist_id, token):
    """Fetch ALL albums (including singles, compilations, etc.) with pagination."""
    url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"
    params = {
        "include_groups": "single,album,appears_on,compilation",
        "limit": 50,  # Max per page
    }
    headers = {"Authorization": f"Bearer {token}"}
    albums = []
    while url:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        albums.extend(data["items"])
        url = data.get("next")  # Next page URL (includes all parameters)
        params = None  # Params already in the next URL
    return albums


def load_last_check_time():
    try:
        with open(LAST_CHECK_FILE, "r") as f:
            ts = f.read().strip()
            return datetime.fromisoformat(ts)
    except FileNotFoundError:
        # First run: use a very old date so everything is considered "new"
        return datetime(2000, 1, 1, tzinfo=timezone.utc)


def save_last_check_time(dt):
    with open(LAST_CHECK_FILE, "w") as f:
        f.write(dt.isoformat())


def send_discord_notification(webhook_url, new_releases):
    """Send a Discord message with the list of new releases."""
    message = "**New releases found!**\n"
    for a in new_releases:
        # Format: - Album name (album_type) – release_date (Spotify link)
        message += f"- [{a['name']}]({a['external_urls']['spotify']}) ({a['album_type']}) – {a['release_date']}\n"

    payload = {"content": message}
    requests.post(webhook_url, json=payload)


def main():
    if (
        CLIENT_ID == "your_spotify_client_id"
        or CLIENT_SECRET == "your_spotify_client_secret"
    ):
        raise SystemExit(
            "Please set your Spotify client ID and secret in the script or as environment variables."
        )

    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    albums = get_all_artist_albums(ARTIST_ID, token)

    print(f"Total releases fetched: {len(albums)}")

    # Sort by release date (newest first)
    albums_sorted = sorted(albums, key=lambda a: a["release_date"], reverse=True)

    # Print the latest 10 releases in the terminal
    print("\nLatest 10 releases (any type):")
    for a in albums_sorted[:10]:
        print(
            f"- {a['name']} ({a['album_type']}) – {a['release_date']} "
            f"{a['external_urls']['spotify']}"
        )

    # Check for new releases since last run
    last_check = load_last_check_time()
    now = datetime.now(timezone.utc)

    new_releases = []
    for album in albums:
        # Convert release_date to datetime
        rd = album["release_date"]
        precision = album["release_date_precision"]
        if precision == "year":
            rd += "-01-01"
        elif precision == "month":
            rd += "-01"
        release_dt = datetime.fromisoformat(rd).replace(tzinfo=timezone.utc)

        if release_dt > last_check:
            new_releases.append(album)

    # If there are new releases, send a Discord notification
    if new_releases:
        print(f"\n✅ {len(new_releases)} new release(s) found since {last_check}!")
        if DISCORD_WEBHOOK_URL and DISCORD_WEBHOOK_URL != "your_discord_webhook_url":
            send_discord_notification(DISCORD_WEBHOOK_URL, new_releases)
            print("Discord notification sent.")
        else:
            print("Discord webhook not configured – skipping notification.")
    else:
        print(f"\nNo new releases since {last_check}.")

    # Update the last check time
    save_last_check_time(now)


if __name__ == "__main__":
    main()
